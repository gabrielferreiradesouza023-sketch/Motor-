"""Synthetic signed permissions; every rejection plants an exposure violation."""

import json
import os
import shutil
from datetime import UTC, date, datetime, timedelta

import pytest
import yaml
from test_gate_c import confirmation_rules
from test_scheduler import seeded

from arb.db import Repository
from arb.launcher import approval as signing
from arb.launcher import confirmation as module
from arb.models import Action, Approval, Decision, Entity, MetricSnapshot, SaleEvent
from arb.scheduler import run_cycle, schedule

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


@pytest.fixture
def candidate(tmp_path, records, request):
    root = tmp_path / "root"
    shutil.copytree("config", root / "config")
    rules = confirmation_rules()
    (root / "config/rules.yaml").write_text(yaml.safe_dump(rules.model_dump()))
    conn = seeded(tmp_path, records)
    with conn:
        entity = Repository(conn, Entity).get("entity")
        entity.gate = "3"
        Repository(conn, Entity).update(entity)
        Repository(conn, MetricSnapshot).add(
            records[4].model_copy(update={"spend_platform_cents": getattr(request, "param", 11284)})
        )
        for n in range(5):
            Repository(conn, SaleEvent).add(
                records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)})
            )
    yield conn, root, rules
    conn.close()


def cycle(candidate, tmp_path, index=0):
    conn, root, _ = candidate
    slot = schedule(date(2026, 10, 5), date(2026, 10, 5))[index]
    return run_cycle(
        conn,
        slot,
        now=slot,
        root=root,
        output=tmp_path / "reports",
        sync_source=lambda db, now: now,
    )


def sign_pending(root, monkeypatch, now=NOW):
    path = next((root / "ops/approvals/pending").glob("gate-c-*.json"))
    monkeypatch.setattr(signing, "is_interactive", lambda: True)
    return signing.sign_file(path, confirm=lambda _: True, now=now)


def write_artifact(path, approval, plan):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"approval": approval.model_dump(mode="json"), "plan": plan}))


def test_unsigned_candidate_pauses_at_g3_cap_and_replay_is_durable(candidate, tmp_path):
    conn, root, rules = candidate
    result = cycle(candidate, tmp_path)
    entity = Repository(conn, Entity).get("entity")
    assert (entity.gate, entity.status, entity.daily_budget_cents) == ("3", "paused", 1000)
    path = next((root / "ops/approvals/pending").glob("gate-c-*.json"))
    approval, plan = signing.read_document(path)
    # Gross 11284 * 1.13 rounds HALF_UP to 12751; G3 cap is 3 * 5000 * .85 =12750.
    assert plan == {
        "kind": "gate_c_confirmation",
        "entity_id": "entity",
        "geo": "CO",
        "offer_id": "offer",
        "confirmation_start_cents": 12751,
        "extra_cap_cents": 15000,
        "total_cap_cents": 27751,
        "expires_at": "2026-10-06T09:00:00-03:00",
    }
    assert approval.status == "pending" and approval.signature is None
    assert approval.max_exposure_cents == 15000 and path.stat().st_mode & 0o777 == 0o600
    actions = Repository(conn, Action).list()
    assert any(a.kind == "pause" for a in actions)
    assert any(a.result == "waiting_approval" for a in actions)
    assert cycle(candidate, tmp_path) == result
    assert Repository(conn, Action).list() == actions
    # Later cycle cannot collect additional traffic from a paused candidate.
    cycle(candidate, tmp_path, 1)
    assert len(Repository(conn, MetricSnapshot).list()) == 1
    assert len(list(path.parent.glob("gate-c-*.json"))) == 1


def test_valid_approval_admits_paused_candidate_without_activation(
    candidate, tmp_path, monkeypatch
):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    path = sign_pending(root, monkeypatch)
    approval, plan = signing.read_document(path)
    cycle(candidate, tmp_path, 1)
    entity = Repository(conn, Entity).get("entity")
    assert (entity.gate, entity.status, entity.daily_budget_cents) == ("C", "paused", 1000)
    actions = Repository(conn, Action).list()
    admit = next(a for a in actions if a.result == "authorized")
    assert admit.approval_id == approval.id
    assert admit.payload_json["output"] == {
        "gate": "C",
        "status": "paused",
        "daily_budget_cents": 1000,
    }
    assert not any(a.kind in {"activate", "scale"} for a in actions)
    module.admit(conn, entity, approval, NOW)
    assert len(Repository(conn, Action).list()) == len(actions)
    # An independent activation was completed by the synthetic operator, not admit().
    with conn:
        entity.status = "active"
        Repository(conn, Entity).update(entity)
        Repository(conn, MetricSnapshot).add(
            MetricSnapshot(
                entity_id=entity.id,
                ts=schedule(date(2026, 10, 5), date(2026, 10, 5))[2],
                impressions=0,
                video_3s_views=0,
                link_clicks=0,
                spend_platform_cents=0,
                bridge_views=0,
                checkout_clicks=0,
            )
        )
    cycle(candidate, tmp_path, 2)
    decisions = Repository(conn, Decision).list()
    confirmed = next(d for d in decisions if d.gate == "C")
    assert confirmed.metrics_json["cap_cents"] == 27751
    assert confirmed.verdict == "pass"


@pytest.mark.parametrize(
    "violation",
    [
        "entity",
        "geo",
        "offer",
        "baseline",
        "extra",
        "total",
        "hash",
        "expired",
        "naive",
        "invalid_date",
        "wrong_date_type",
        "unsigned",
        "rejected",
        "future_decision",
        "no_decision",
        "low_exposure",
        "extra_field",
        "bool_money",
        "wrong_kind",
    ],
)
def test_wrong_permission_never_admits_or_leaves_c_active(
    candidate, tmp_path, monkeypatch, violation
):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    path = sign_pending(root, monkeypatch)
    approval, plan = signing.read_document(path)
    mapping = {
        "entity": ("entity_id", "other"),
        "geo": ("geo", "MX"),
        "offer": ("offer_id", "other"),
        "baseline": ("confirmation_start_cents", 1),
        "extra": ("extra_cap_cents", 1),
        "total": ("total_cap_cents", 1),
        "expired": ("expires_at", NOW.isoformat()),
        "naive": ("expires_at", "2099-01-01T00:00:00"),
        "invalid_date": ("expires_at", "invalid"),
        "wrong_date_type": ("expires_at", None),
        "extra_field": ("unexpected", "value"),
        "bool_money": ("extra_cap_cents", True),
        "wrong_kind": ("kind", "scale"),
    }
    if violation in mapping:
        key, value = mapping[violation]
        plan[key] = value
        approval.plan_hash = module.digest(plan)
    elif violation == "hash":
        plan["total_cap_cents"] += 1
    elif violation == "unsigned":
        approval.signature = None
    elif violation == "rejected":
        approval.status = "rejected"
    elif violation == "future_decision":
        approval.decided_at = NOW + timedelta(days=2)
    elif violation == "no_decision":
        approval.decided_at = None
    elif violation == "low_exposure":
        approval.max_exposure_cents = 1
    if violation not in {"hash", "unsigned", "wrong_kind"}:
        approval = signing.sign(approval)  # even honestly signed context mismatch must fail
    write_artifact(path, approval, plan)
    cycle(candidate, tmp_path, 1)
    entity = Repository(conn, Entity).get("entity")
    assert (entity.gate, entity.status) == ("3", "paused")
    with conn:
        entity.gate, entity.status = "C", "active"
        Repository(conn, Entity).update(entity)
    cycle(candidate, tmp_path, 2)
    assert Repository(conn, Entity).get(entity.id).status == "paused"
    decision = next(d for d in Repository(conn, Decision).list() if d.gate == "C")
    assert decision.rule_id == "gC.approval" and decision.verdict == "insufficient_data"
    assert any(a.result == "waiting_approval" for a in Repository(conn, Action).list())


@pytest.mark.parametrize("baseline", [None, True, -1, 1.5])
def test_missing_or_corrupt_baseline_cannot_authorize(records, baseline, tmp_path):
    with pytest.raises(ValueError, match="baseline"):
        module.authorized(records[3], baseline, confirmation_rules(), NOW, tmp_path)


def test_off_c_cannot_authorize(records, tmp_path):
    from arb.rules import load_rules

    with pytest.raises(ValueError, match="desligado"):
        module.authorized(records[3], 1, load_rules(), NOW, tmp_path)


@pytest.mark.parametrize(
    "artifact",
    ["symlink", "hardlink", "directory", "invalid", "name", "wrong_type", "missing_plan"],
)
def test_untrusted_artifact_path_never_authorizes(candidate, tmp_path, monkeypatch, artifact):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    path = sign_pending(root, monkeypatch)
    approval, plan = signing.read_document(path)
    if artifact == "symlink":
        target = path.with_suffix(".other")
        path.rename(target)
        path.symlink_to(target)
    elif artifact == "hardlink":
        os.link(path, path.with_suffix(".other"))
    elif artifact == "directory":
        path.unlink()
        path.mkdir()
    elif artifact == "invalid":
        path.write_text("{")
    elif artifact == "name":
        path.rename(path.parent / "gate-c-wrong.json")
    elif artifact == "wrong_type":
        path.write_text("[]")
    else:
        path.write_text(approval.model_dump_json())
    with pytest.raises(ValueError):
        module.authorized(Repository(conn, Entity).get("entity"), 12751, rules, NOW, path.parent)


def test_proposal_expiry_renewal_and_corrupt_collision(candidate, tmp_path):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    entity = Repository(conn, Entity).get("entity")
    directory = root / "ops/approvals/pending"
    first = next(directory.glob("*.json"))
    later = NOW + timedelta(days=1)
    new = module.propose(conn, entity, 12751, rules, later, directory)
    assert new != first
    assert signing.read_document(new)[1]["expires_at"] == (later + timedelta(days=1)).isoformat()
    # A corrupt file already occupying the canonical path must not be silently reused.
    new.write_text("{")
    with pytest.raises(ValueError, match="divergente"):
        module.propose(conn, entity, 12751, rules, later, directory)


def test_proposal_failure_does_not_stop_pause(candidate, tmp_path):
    conn, root, _ = candidate
    (root / "ops/approvals").mkdir(parents=True)
    (root / "ops/approvals/pending").write_text("not a directory")
    result = cycle(candidate, tmp_path)
    assert Repository(conn, Entity).get("entity").status == "paused"
    assert any("confirmation_proposal_failed" in a for a in result["alerts"])
    result = cycle(candidate, tmp_path, 1)
    assert any("confirmation_proposal_failed" in a for a in result["alerts"])


def test_activation_and_direct_remote_path_cannot_bypass_candidate_permission(
    candidate, tmp_path, monkeypatch
):
    from arb.launcher.actions import activate
    from arb.remote.fake import FakeMeta
    from arb.remote.journal import perform

    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    monkeypatch.setattr(module, "load_rules", lambda: rules)
    entity = Repository(conn, Entity).get("entity")
    with pytest.raises(ValueError, match="C exige"):
        activate(conn, entity.id, "fake", now=NOW, approval_dir=root / "ops/approvals/approved")
    writer = FakeMeta()
    with pytest.raises(ValueError, match="C exige"):
        perform(
            conn,
            writer,
            entity,
            "activate",
            "bypass",
            context={},
            now=NOW,
            confirmation_dir=root / "ops/approvals/approved",
        )
    assert not writer.calls
    path = sign_pending(root, monkeypatch)
    module.require_family(conn, entity.id, directory=path.parent, now=NOW)
    # This approval is not an activation approval; the original gate still refuses.
    with pytest.raises(ValueError):
        activate(conn, entity.id, path.stem, now=NOW, approval_dir=path.parent)
    assert Repository(conn, Entity).get(entity.id).status == "paused"


def test_parent_activation_includes_c_descendant(candidate, tmp_path, monkeypatch):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    with conn:
        child = Repository(conn, Entity).get("entity")
        parent = child.model_copy(update={"id": "parent", "kind": "campaign", "gate": "1"})
        Repository(conn, Entity).add(parent)
        child.parent_id, child.gate = parent.id, "C"
        Repository(conn, Entity).update(child)
        Repository(conn, Entity).add(
            child.model_copy(update={"id": "other", "parent_id": None, "gate": "0"})
        )
    monkeypatch.setattr(module, "load_rules", lambda: rules)
    with pytest.raises(ValueError, match="C exige"):
        module.require_family(conn, "parent", directory=root / "ops/approvals/approved", now=NOW)


def test_scheduler_simulation_reference_and_no_overwrite(tmp_path):
    from arb.db import connect
    from arb.rules import load_rules
    from arb.scheduler.simulation import simulate

    target = tmp_path / "sim.db"
    result = simulate(target, output=tmp_path / "reports")
    assert result["mode"] == "simulation" and result["cycle_count"] == 9
    db = connect(target)
    try:
        assert (
            sum(a.kind == "activate" or a.kind == "scale" for a in Repository(db, Action).list())
            == 0
        )
        # Published caps independently bound every paused entity after the 9-cycle simulation.
        assert (
            result["snapshots"] == db.execute("SELECT count(*) FROM metric_snapshots").fetchone()[0]
        )
        assert result["paused"] > 0
        assert all(
            e.daily_budget_cents <= load_rules().controls.total_cap_cents
            for e in Repository(db, Entity).list()
        )
    finally:
        db.close()
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        simulate(target, output=tmp_path / "other")
    assert target.read_bytes() == before


@pytest.mark.parametrize("candidate", [1000], indirect=True)
def test_before_g3_cap_candidate_keeps_budget_and_lost_proposal_is_recreated(
    candidate, tmp_path, monkeypatch
):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    entity = Repository(conn, Entity).get("entity")
    assert (entity.gate, entity.status, entity.daily_budget_cents) == ("3", "active", 1000)
    assert not any(a.kind == "pause" for a in Repository(conn, Action).list())
    monkeypatch.setattr(module, "load_rules", lambda: rules)
    module.require_family(conn, entity.id, directory=root / "ops/approvals/approved", now=NOW)
    directory = root / "ops/approvals/pending"
    path = next(directory.glob("*.json"))
    before = path.read_bytes()
    path.unlink()  # intentional recovery violation, durable baseline/Approval stay intact
    assert (
        module.propose(
            conn,
            entity,
            1130,
            rules,
            NOW.astimezone(schedule(date(2026, 10, 5), date(2026, 10, 5))[0].tzinfo),
            directory,
        ).read_bytes()
        == before
    )
    # Non-C entity and a family that excludes this candidate never needs a C approval.
    with conn:
        Repository(conn, Entity).add(entity.model_copy(update={"id": "unrelated", "gate": "1"}))
    module.require_family(conn, "unrelated", directory=directory, now=NOW)


def test_signature_does_not_override_project_brake(candidate, tmp_path, monkeypatch):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    sign_pending(root, monkeypatch)
    rules = rules.model_copy(
        update={"controls": rules.controls.model_copy(update={"daily_cap_cents": 10000})}
    )
    (root / "config/rules.yaml").write_text(yaml.safe_dump(rules.model_dump()))
    with conn:
        entity = Repository(conn, Entity).get("entity")
        entity.status = "active"  # synthetic separately authorized activation
        Repository(conn, Entity).update(entity)
        Repository(conn, MetricSnapshot).add(
            MetricSnapshot(
                entity_id=entity.id,
                ts=schedule(date(2026, 10, 5), date(2026, 10, 5))[1],
                impressions=0,
                video_3s_views=0,
                link_clicks=0,
                spend_platform_cents=0,
                bridge_views=0,
                checkout_clicks=0,
            )
        )
    result = cycle(candidate, tmp_path, 1)
    assert any("daily_cap" in a for a in result["alerts"])
    assert Repository(conn, Entity).get(entity.id).status == "paused"
    assert any(d.gate == "C" and d.verdict == "pass" for d in Repository(conn, Decision).list())


def test_paused_c_expiration_creates_fresh_proposal(candidate, tmp_path, monkeypatch):
    conn, root, rules = candidate
    cycle(candidate, tmp_path)
    sign_pending(root, monkeypatch)
    cycle(candidate, tmp_path, 1)
    later = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    run_cycle(
        conn,
        later,
        now=later,
        root=root,
        output=tmp_path / "reports",
        sync_source=lambda db, now: now,
    )
    entity = Repository(conn, Entity).get("entity")
    assert (entity.gate, entity.status) == ("C", "paused")
    proposal = next((root / "ops/approvals/pending").glob("gate-c-*.json"))
    approval, plan = signing.read_document(proposal)
    assert approval.signature is None and approval.status == "pending"
    assert datetime.fromisoformat(plan["expires_at"]) == later + timedelta(hours=24)


def test_crash_after_durable_proposal_resumes_without_duplicate_permission(
    candidate, tmp_path, monkeypatch
):
    import arb.scheduler as scheduler

    conn, root, rules = candidate
    original = scheduler._confirmation_audit

    def crash(*args):
        original(*args)
        raise RuntimeError("synthetic crash after durable proposal, before checkpoint")

    monkeypatch.setattr(scheduler, "_confirmation_audit", crash)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        cycle(candidate, tmp_path)
    assert len(list((root / "ops/approvals/pending").glob("*.json"))) == 1
    assert len(Repository(conn, Decision).list()) == 1
    monkeypatch.setattr(scheduler, "_confirmation_audit", original)
    result = cycle(candidate, tmp_path)
    assert result["stages"] == ["sync", "rules", "actions", "report", "alerts"]
    assert Repository(conn, Entity).get("entity").status == "paused"
    assert len(Repository(conn, Decision).list()) == 1
    assert len(Repository(conn, Approval).list()) == 1
    assert sum(a.result == "waiting_approval" for a in Repository(conn, Action).list()) == 1
    assert sum(a.kind == "pause" for a in Repository(conn, Action).list()) == 1
    assert cycle(candidate, tmp_path) == result
