"""Ensaio descartável. Nunca opera o banco, chave ou configuração do humano."""

import os
import shutil
import sqlite3
import sys
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from arb.analyst import pnl
from arb.analyst.report import generate_report
from arb.creative import generate_angles
from arb.creative.approve import apply as creative_apply
from arb.creative.approve import propose as creative_propose
from arb.creative.copy import generate_copies
from arb.db import Repository, backup_daily, connect, migrate
from arb.db.checkpoint import drill as backup_drill
from arb.db.restore import restore_new
from arb.launcher import plan, plan_hash
from arb.launcher.actions import activate, activation_intent, intent_hash
from arb.launcher.approval import public_hex, read_document, sign_file, verify
from arb.launcher.execute import execute, require_simulation
from arb.launcher.scale import apply as scale_apply
from arb.launcher.scale import digest
from arb.launcher.scale import propose as scale_propose
from arb.ledger import pending
from arb.meta.read import MetaReadError, Reader
from arb.metrics import spend_gross
from arb.models import Action, Angle, Approval, Creative, Entity, LaunchPlan, MetricSnapshot, Offer
from arb.quarantine import current, release
from arb.reconcile import reconcile
from arb.remote.fake import FakeMeta
from arb.scheduler import run_cycle, schedule
from arb.scout import import_adlibrary, import_offers
from arb.scout.approve import apply as offer_apply
from arb.scout.ranking import propose as offer_propose
from arb.scout.ranking import rank

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 10, 5, 12, tzinfo=UTC)


@contextmanager
def _console():
    # TTY só do ensaio, com confirm callbacks e arquivos inteiramente temporários.
    master, slave = os.openpty()
    try:
        with os.fdopen(os.dup(slave), "r") as inp, os.fdopen(os.dup(slave), "w") as out:
            previous = sys.stdin, sys.stdout
            sys.stdin, sys.stdout = inp, out
            try:
                yield
            finally:
                sys.stdin, sys.stdout = previous
    finally:
        os.close(master)
        os.close(slave)


@contextmanager
def _sandbox(directory):
    shutil.copytree(ROOT / "config", directory / "config")
    # Mesma chave pública sintética do conftest; privada criada só neste tmpdir.
    raw = bytes(range(32))
    key = Ed25519PrivateKey.from_private_bytes(raw)
    private_path = directory / "synthetic-private.key"
    private_path.write_text(raw.hex())
    private_path.chmod(0o600)
    settings = directory / "config/settings.yaml"
    body = yaml.safe_load(settings.read_text())
    body["approval_public_key"] = public_hex(key)
    settings.write_text(yaml.safe_dump(body))
    previous_cwd = Path.cwd()
    previous_pointer = os.environ.get("APPROVAL_PRIVATE_KEY_FILE")
    os.environ["APPROVAL_PRIVATE_KEY_FILE"] = str(private_path)
    os.chdir(directory)
    try:
        with _console():
            yield
    finally:
        os.chdir(previous_cwd)
        if previous_pointer is None:
            os.environ.pop("APPROVAL_PRIVATE_KEY_FILE", None)
        else:
            os.environ["APPROVAL_PRIVATE_KEY_FILE"] = previous_pointer


def _signed(path, now):
    signed = sign_file(path, lambda _: True, now=now)
    return read_document(signed)[0], signed.parent


def _approval(directory, identity, kind, fingerprint, amount, now):
    directory.mkdir(parents=True, exist_ok=True)
    value = Approval(
        id=identity,
        kind=kind,
        plan_hash=fingerprint,
        summary="Ensaio sintético descartável",
        max_exposure_cents=amount,
        status="pending",
    )
    path = directory / (identity + ".json")
    path.write_text(value.model_dump_json())
    return _signed(path, now)


def _refused(operation, fragment=None):
    try:
        operation()
    except (ValueError, sqlite3.DatabaseError, MetaReadError) as error:
        if fragment and fragment not in str(error):
            raise ValueError("recusa diferente da barreira esperada") from None
        return True
    raise ValueError("barreira esperada não recusou a operação")


def _invariants(conn, writer, restored, value, expected_spend, quarantine_blocked):
    actions = Repository(conn, Action).list()
    intents = [a for a in actions if a.result == "intent"]
    by_key = {a.payload_json["key"]: a for a in intents}
    authority = all(not a.live for a in actions)
    original_entities = {e.id: e for e in value.entities}
    for attempt in intents:
        operation = attempt.payload_json["operation"]
        if operation == "pause":
            continue
        approval = Repository(conn, Approval).get(attempt.approval_id)
        context = attempt.payload_json["context"]
        source = Entity.model_validate(attempt.payload_json["source"])
        try:
            verify(approval)
            if operation == "create":
                reference = LaunchPlan.model_validate(context)
                kind, fingerprint, amount = (
                    "launch",
                    plan_hash(reference),
                    reference.daily_budget_cents,
                )
            elif operation == "activate":
                # Neste fluxo todas as ativações precedem a escala: verba do plano assinado.
                kind, fingerprint = "activate", intent_hash(context)
                amount = original_entities[source.parent_id].daily_budget_cents
            else:
                kind, fingerprint, amount = "scale", digest(context), context["to_budget_cents"]
            authority &= (
                approval.kind == kind
                and approval.plan_hash == fingerprint
                and approval.status == "approved"
                and approval.decided_at <= attempt.ts
                and approval.max_exposure_cents >= amount
            )
        except (ValueError, AttributeError, KeyError, TypeError):
            authority = False
    checks = {
        "authority": authority,
        "audit": all(
            call["key"] in by_key
            and by_key[call["key"]].payload_json["operation"] == call["operation"]
            for call in writer.calls
        ),
        "unique": len({e["key"] for e in writer.effects}) == len(writer.effects)
        and len(writer.entities) == len(value.entities)
        and len({e.id for e in writer.entities.values()}) == len(value.entities),
        "paused": not pending(conn)
        and all(e.status == "paused" for e in writer.entities.values())
        and all(e.status == "paused" for e in Repository(conn, Entity).list()),
        "quarantine": quarantine_blocked
        and current(restored) is None
        and any(a.kind == "restore_release" for a in Repository(restored, Action).list()),
        "totals": pnl(conn)["totals"]["spend_gross"] == spend_gross(expected_spend)
        and pnl(restored)["totals"]["spend_gross"] == spend_gross(expected_spend),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ValueError("invariantes violadas: " + ", ".join(failed))
    return checks


def _scenario(directory, seed, inject):
    now = BASE + timedelta(hours=24)
    proposals = directory / "ops/approvals/pending"
    with closing(connect(directory / "data/engine.db")) as conn:
        migrate(conn)
        ranked, _ = rank(
            import_offers(ROOT / "examples/scout/offers.csv"),
            import_adlibrary(ROOT / "examples/scout/adlibrary.csv"),
        )
        approval, approved = _signed(offer_propose(conn, ranked, proposals), BASE)
        offer_apply(conn, approval.id, directory=approved, now=BASE)
        offer = Repository(conn, Offer).list()[0]
        angles = generate_angles(offer, [])[: 1 + seed % 3]
        copies = [c for a in angles for c in generate_copies(offer, a, region="CO")]
        with conn:
            for record in angles:
                Repository(conn, Angle).add(record)
            for record in copies:
                Repository(conn, Creative).add(record)
        approval, approved = _signed(creative_propose(conn, offer.id, directory=proposals), BASE)
        creative_apply(conn, approval.id, directory=approved, now=BASE)
        value = plan(
            Repository(conn, Offer).get(offer.id),
            Repository(conn, Angle).list(),
            Repository(conn, Creative).list(),
            geo="CO",
            daily_budget_cents=2000 * len(angles),
            destination_url="https://bridge.example.test/oferta",
        )
        launch_approval, approved = _approval(
            proposals, "launch", "launch", plan_hash(value), value.daily_budget_cents, BASE
        )
        writer = FakeMeta()
        launch = execute(
            conn, value, launch_approval.id, approval_dir=approved, writer=writer, now=BASE
        )
        assert (
            execute(conn, value, launch_approval.id, approval_dir=approved, writer=writer, now=BASE)
            == launch
        )
        ads = [e for e in Repository(conn, Entity).list() if e.kind == "ad"][:2]
        for index, ad in enumerate(ads):
            approval, approved = _approval(
                proposals,
                "activate-" + str(index),
                "activate",
                intent_hash(activation_intent(ad)),
                2000,
                BASE,
            )
            activate(conn, ad.id, approval.id, approval_dir=approved, writer=writer, now=BASE)
        backups = directory / "data/backups"
        active_backup = backup_daily(conn, backups, day=BASE.date())
        slots = schedule(BASE.date(), BASE.date())[:2]
        scenarios = {}
        with closing(
            connect(restore_new(active_backup, directory / "active-copy.db"))
        ) as active_copy:
            assert any(e.status == "active" for e in Repository(active_copy, Entity).list())
            scenarios["restore_active"] = _refused(
                lambda: release(active_copy, reader=writer, confirm=lambda: True, now=BASE),
                "PAUSED",
            )
            _refused(
                lambda: run_cycle(active_copy, slots[0], now=slots[0], root=directory), "quarentena"
            )
        per_ad = 350 + seed % 100

        def traffic(db, stamp):
            first = stamp == slots[0]
            with db:
                for ad in ads:
                    Repository(db, MetricSnapshot).add(
                        MetricSnapshot(
                            entity_id=ad.id,
                            ts=stamp,
                            impressions=1000 if first else 10000,
                            video_3s_views=400 if first else 0,
                            link_clicks=30 if first else 0,
                            spend_platform_cents=150 if first else per_ad,
                            bridge_views=30 if first else 0,
                            checkout_clicks=5 if first else 0,
                        )
                    )
            return stamp

        run_cycle(
            conn,
            slots[0],
            now=slots[0],
            root=directory,
            output=directory / "reports",
            sync_source=traffic,
            writer=writer,
        )
        original_pause = writer.pause

        def crash(identifier, key):
            original_pause(identifier, key)
            writer.pause = original_pause
            raise KeyboardInterrupt("queda sintética após efeito")

        writer.pause = crash
        try:
            run_cycle(
                conn,
                slots[1],
                now=slots[1],
                root=directory,
                output=directory / "reports",
                sync_source=traffic,
                writer=writer,
            )
        except KeyboardInterrupt:
            scenarios["interrupted_cycle"] = True
        else:
            raise ValueError("queda não exercitada")
        states = {p["state"] for p in pending(conn)}
        scenarios["orphan_intent"] = "orphan" in states
        assert reconcile(conn, writer, now=slots[1])["alerts"] == []
        writer.fail_next("pause", "after_timeout")
        result = run_cycle(
            conn,
            slots[1],
            now=slots[1],
            root=directory,
            output=directory / "reports",
            sync_source=traffic,
            writer=writer,
        )
        scenarios["pause_uncertain"] = any(p["state"] == "uncertain" for p in pending(conn))
        assert reconcile(conn, writer, now=slots[1])["alerts"] == []
        effects = len(writer.effects)
        assert (
            run_cycle(
                conn,
                slots[1],
                now=slots[1],
                root=directory,
                output=directory / "reports",
                writer=writer,
            )
            == result
        )
        assert len(writer.effects) == effects
        adset = next(e for e in Repository(conn, Entity).list() if e.kind == "adset")
        approval, approved = _signed(
            scale_propose(conn, adset.id, 2400, directory=proposals, now=now), now
        )
        scale_apply(conn, approval.id, directory=approved, now=now, writer=writer)
        backup = backup_daily(conn, backups, day=now.date())
        proof = backup_drill(backups, now=now)
        assert proof["status"] == "passed"
        broken = directory / "corrupt.db"
        broken.write_bytes(b"planted corruption")
        scenarios["corrupt_backup"] = _refused(
            lambda: restore_new(broken, directory / "bad-copy.db")
        )
        assert not (directory / "bad-copy.db").exists()

        def expired(request):
            assert request.method == "GET"
            return httpx.Response(400, json={"error": {"code": 190}})

        with httpx.Client(transport=httpx.MockTransport(expired), trust_env=False) as client:
            reader = Reader("synthetic-token", "act_123", "v99.0", client=client, attempts=1)
            scenarios["token_190"] = _refused(reader.account, "190")
        with closing(connect(restore_new(backup, directory / "recovered.db"))) as restored:
            blocked = _refused(
                lambda: execute(
                    restored,
                    value,
                    launch_approval.id,
                    approval_dir=approved,
                    writer=writer,
                    now=now,
                ),
                "quarentena",
            )
            release(restored, reader=writer, confirm=lambda: True, now=now)
            scenarios["quarantine"] = blocked and current(restored) is None
            generate_report(restored, directory / "restored-report", now=now)
            if inject:
                inject(conn, writer, restored)
            checks = _invariants(conn, writer, restored, value, 2 * (150 + per_ad), blocked)
            if not all(scenarios.values()):
                raise ValueError("cenário não exercitado")
            return {
                "seed": seed,
                "mode": "synthetic-only",
                "entities": len(value.entities),
                "remote_calls": len(writer.calls),
                "remote_effects": len(writer.effects),
                "cycles": 2,
                "pending": len(pending(conn)),
                "invariants": checks,
                "scenarios": scenarios,
                "totals": {
                    "platform_cents": 2 * (150 + per_ad),
                    "gross_cents": pnl(conn)["totals"]["spend_gross"],
                    "profit_cents": pnl(conn)["totals"]["profit_cents"],
                },
                "backup_drill": {name: proof[name] for name in ("status", "counts", "quarantined")},
            }


def run(seed: int, *, _inject=None) -> dict:
    require_simulation()
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed deve ser inteiro entre 0 e 2147483647")
    with TemporaryDirectory(prefix="arb-drill-") as temporary:
        directory = Path(temporary)
        with _sandbox(directory):
            return _scenario(directory, seed, _inject)
