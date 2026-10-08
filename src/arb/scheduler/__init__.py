"""Ciclos locais protegidos por lock de processo e checkpoints idempotentes."""

import fcntl
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

import yaml

from arb import safety
from arb.analyst import pnl
from arb.analyst.report import generate_report
from arb.config import Settings
from arb.db import Repository, backup_daily
from arb.launcher.actions import pause
from arb.metrics import effective_refund_rates
from arb.models import (
    Action,
    Creative,
    Decision,
    Entity,
    MetricAdjustment,
    MetricSnapshot,
    Offer,
    SaleEvent,
)
from arb.permissions import private_open
from arb.remote.fake import FakeMeta
from arb.rules import confirmation_context, controls, evaluate, load_rules, winner_gates

ZONE = ZoneInfo("America/Sao_Paulo")


def schedule(
    start: date, end: date, *, cycles: tuple[str, ...] = ("09:00", "18:00", "23:30")
) -> list[datetime]:
    if end < start or (end - start).days > 366:
        raise ValueError("intervalo inválido")
    result = []
    day = start
    while day <= end:
        result.extend(datetime.combine(day, time.fromisoformat(slot), ZONE) for slot in cycles)
        day += timedelta(days=1)
    return sorted(set(result))


def family_ids(entity: Entity, entities: list[Entity]) -> set[str]:
    family = {entity.id}
    while True:
        expanded = family | {e.id for e in entities if e.parent_id in family}
        if expanded == family:
            return family
        family = expanded


def run_cycle(
    connection: sqlite3.Connection,
    scheduled_at: datetime,
    *,
    sync_source: Callable[[sqlite3.Connection, datetime], datetime | None] | None = None,
    report_fn: Callable = generate_report,
    notify: Callable[[list[str]], object] | None = None,
    root: Path = Path("."),
    output: Path = Path("reports"),
    now: datetime | None = None,
    writer=None,
) -> dict:
    """Sync injetável somente leitura/local; falta/falha congela entidades simuladas.

    Nunca solicita integração ou envio externos por padrão. Não modifica status
    observado de entidades Meta. Falhas de alerta não interrompem proteção de verba.
    """
    from arb.quarantine import require_released

    require_released(connection)
    safety.live_mode()  # valide o modo; escrita só passa pelo caminho auditado de pausa
    now = now or datetime.now(UTC)
    settings = Settings.model_validate(yaml.safe_load((root / "config/settings.yaml").read_text()))
    rules = load_rules(root / "config/rules.yaml")
    if now.utcoffset() is None or scheduled_at.utcoffset() is None or scheduled_at > now:
        raise ValueError("ciclo precisa ter fuso e não estar no futuro")
    local = scheduled_at.astimezone(ZONE)
    if local.strftime("%H:%M") not in settings.cycles or local.second or local.microsecond:
        raise ValueError("horário não pertence aos ciclos São Paulo")
    if connection.in_transaction:
        raise ValueError("ciclo requer commit anterior")
    database = Path(connection.execute("PRAGMA database_list").fetchone()[2])
    if not str(database) or str(database) == ".":
        raise ValueError("scheduler exige banco em arquivo")
    with private_open(
        database.with_suffix(database.suffix + ".scheduler.lock"), append=True
    ) as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("outro ciclo está em execução") from exc
        return _run(
            connection,
            scheduled_at,
            now,
            sync_source,
            report_fn,
            notify,
            root,
            output,
            settings,
            rules,
            writer,
        )


def _run(
    connection,
    scheduled_at,
    now,
    sync_source,
    report_fn,
    notify,
    root,
    output,
    settings,
    rules,
    writer,
):
    key = scheduled_at.astimezone(UTC).isoformat()
    previous = connection.execute(
        "SELECT status,payload FROM scheduler_runs WHERE id=?", (key,)
    ).fetchone()
    if previous and previous[0] in {"complete", "skipped"}:
        return json.loads(previous[1])
    result = (
        json.loads(previous[1])
        if previous
        else {
            "id": key,
            "stages": [],
            "alerts": [],
            "decisions": [],
            "pauses": [],
            "collection": None,
        }
    )
    result.pop("error_kind", None)

    def checkpoint(status="running"):
        with connection:
            connection.execute(
                "INSERT INTO scheduler_runs VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload",
                (key, now.isoformat(), status, json.dumps(result, sort_keys=True)),
            )

    checkpoint()
    try:
        if "sync" not in result["stages"]:
            try:
                collection = sync_source(connection, now) if sync_source else None
                if collection is not None and (collection.utcoffset() is None or collection > now):
                    raise ValueError("coleta inválida")
                result["collection"] = collection.isoformat() if collection else None
            except Exception:
                connection.rollback()
                result["collection"] = None
                result["alerts"].append("sync_failed: coleta incompleta; proteção mantida")
            result["stages"].append("sync")
            checkpoint()
        collection = datetime.fromisoformat(result["collection"]) if result["collection"] else None
        stale = collection is None or now - collection > timedelta(
            hours=rules.controls.stale_after_hours
        )
        from arb.smoke import ids as smoke_ids
        from arb.smoke import report as smoke_report

        smoke = smoke_ids(connection)
        entities = Repository(connection, Entity).list()
        snapshots = Repository(connection, MetricSnapshot).list()
        adjustments = Repository(connection, MetricAdjustment).list()
        sales = Repository(connection, SaleEvent).list()
        offers = {o.id: o for o in Repository(connection, Offer).list()}
        rates = effective_refund_rates(
            offers.values(),
            entities,
            sales,
            settings.refund_rate,
            exclude_ids={
                r[0] for r in connection.execute("SELECT entity_id FROM acceptance_test_entities")
            },
        )
        creatives = {c.id: c for c in Repository(connection, Creative).list()}
        if "rules" not in result["stages"]:
            for entity in entities:
                if entity.id in smoke or entity.status != "active" or entity.gate == "0":
                    continue
                family = family_ids(entity, entities)
                leaves = family - {e.parent_id for e in entities if e.id in family}
                items = [s for s in snapshots if s.entity_id in leaves]
                stamp = max((s.ts for s in items), default=now - timedelta(hours=7))
                if stale:
                    stamp = min(stamp, now - timedelta(hours=7))
                totals = {
                    field: sum(getattr(s, field) for s in items)
                    + sum(a.deltas.get(field, 0) for a in adjustments if a.entity_id in leaves)
                    for field in (
                        "impressions",
                        "video_3s_views",
                        "link_clicks",
                        "spend_platform_cents",
                        "bridge_views",
                        "checkout_clicks",
                    )
                }
                combined = MetricSnapshot(entity_id=entity.id, ts=stamp, **totals)
                baseline, confirmed = confirmation_context(
                    entity, Repository(connection, Decision).list()
                )
                decision = evaluate(
                    entity,
                    combined,
                    [s for s in sales if s.matched_entity_id in leaves],
                    offers[entity.offer_id].commission_brl_cents,
                    rules,
                    now,
                    video=entity.creative_id not in creatives
                    or creatives[entity.creative_id].format == "video",
                    media_tax_rate=settings.media_tax_rate,
                    refund_rate=rates.get(entity.id, settings.refund_rate),
                    confirmation_start_cents=baseline,
                    confirmed=confirmed,
                )
                decision.id = str(uuid5(NAMESPACE_URL, key + ":" + entity.id))
                with connection:
                    if Repository(connection, Decision).get(decision.id) is None:
                        Repository(connection, Decision).add(decision)
                        if (
                            rules.gate_C is not None
                            and entity.gate == "3"
                            and decision.verdict == "pass"
                        ):
                            entity.gate = "C"
                            Repository(connection, Entity).update(entity)
                result["decisions"].append(decision.id)
            result["decisions"] = sorted(set(result["decisions"]))
            result["stages"].append("rules")
            checkpoint()
        if "actions" not in result["stages"]:
            data = pnl(
                connection, media_tax_rate=settings.media_tax_rate, refund_rate=settings.refund_rate
            )
            # Gastos do dia por period_start; receitas do dia por timestamp da venda,
            # sem reciclar receita esperada no caixa.
            day = now.astimezone(ZONE).date()
            daily = next(
                (row for row in data["groups"]["daily"] if row["key"] == day.isoformat()), {}
            )
            revenue = sum(
                int(s.commission_cents * (1 - rates.get(s.matched_entity_id, settings.refund_rate)))
                for s in sales
                if s.status == "approved"
                and s.matched_entity_id is not None
                and s.ts.astimezone(ZONE).date() == day
            )
            decisions = Repository(connection, Decision).list()
            brakes = controls(
                rules,
                day_spend_cents=daily.get("spend_gross", 0),
                day_revenue_cents=revenue,
                total_spend_cents=data["totals"]["spend_gross"],
                passed_gate_2=len(
                    {
                        d.entity_id
                        for d in decisions
                        if d.entity_id not in smoke and d.gate == "2" and d.verdict == "pass"
                    }
                ),
                validated_combos=len(
                    {
                        d.entity_id
                        for d in decisions
                        if d.entity_id not in smoke
                        and d.gate in winner_gates(rules)
                        and d.verdict == "pass"
                    }
                ),
            )
            result["alerts"].extend(brakes)
            result["alerts"].extend(
                alert
                for row in smoke_report(connection, media_tax_rate=settings.media_tax_rate)[
                    "campaigns"
                ]
                for alert in row["alerts"]
            )
            if stale:
                result["alerts"].append("stale: dados atrasados/ausentes; simulação congelada")
            targets = {e.id for e in entities if e.status == "active"} if brakes or stale else set()
            for decision_id in result["decisions"]:
                d = Repository(connection, Decision).get(decision_id)
                if d.verdict == "kill" or (
                    d.metrics_json["spend_gross"] >= d.metrics_json["cap_cents"]
                    and not (rules.gate_C is not None and d.gate == "3" and d.verdict == "pass")
                ):
                    entity = next(e for e in entities if e.id == d.entity_id)
                    targets |= family_ids(entity, entities)
            targets -= smoke
            covered = set()
            priority = {"campaign": 0, "adset": 1, "ad": 2}
            ordered = sorted(
                targets,
                key=lambda eid: (priority[next(e.kind for e in entities if e.id == eid)], eid),
            )
            for entity_id in ordered:
                if entity_id in covered:
                    continue
                entity = Repository(connection, Entity).get(entity_id)
                if entity.meta_id and not safety.live_mode() and not isinstance(writer, FakeMeta):
                    result["alerts"].append(
                        "remote_pause_pending: intervenção humana na Meta necessária"
                    )
                    continue
                try:
                    action = pause(
                        connection,
                        entity_id,
                        reason="scheduler: regra/teto/dados atrasados/freio",
                        now=now,
                        writer=writer,
                    )
                except ValueError:
                    result["alerts"].append(
                        f"pause_failed: {entity_id}; reconciliar antes de repetir"
                    )
                    continue
                if action:
                    result["pauses"].append(action.id)
                if (
                    entity.meta_id
                    and Repository(connection, Entity).get(entity_id).status == "paused"
                ):
                    covered |= family_ids(entity, entities) - {entity_id}
            result["stages"].append("actions")
            checkpoint()
        if "report" not in result["stages"]:
            from arb.scheduler.alerts import collect

            result["alerts"] = collect(
                connection, result["alerts"], approval_dir=root / "ops/approvals/pending"
            )
            result["report"] = str(
                report_fn(
                    connection,
                    output,
                    approval_dir=root / "ops/approvals/pending",
                    now=now,
                    alert_messages=result["alerts"],
                )
            )
            backup_daily(connection, database_backups(connection), day=now.astimezone(UTC).date())
            result["stages"].append("report")
            checkpoint()
        if "alerts" not in result["stages"]:
            from arb.scheduler.alerts import collect, dispatch

            result["alerts"] = collect(
                connection, result["alerts"], approval_dir=root / "ops/approvals/pending"
            )
            result["notification"] = dispatch(connection, key, result["alerts"], now=now)
            hook_id = str(uuid5(NAMESPACE_URL, key + ":notify-hook"))
            if notify and Repository(connection, Action).get(hook_id) is None:
                with connection:
                    Repository(connection, Action).add(
                        Action(
                            id=hook_id,
                            ts=now,
                            actor="engine",
                            kind="notify_hook",
                            live=False,
                            payload_json={"cycle_id": key},
                            result="uncertain",
                        )
                    )
                try:
                    notify(result["alerts"])
                except Exception:
                    result["alerts"].append("notification_failed: consultar relatório local")
                else:
                    with connection:
                        Repository(connection, Action).add(
                            Action(
                                id=hook_id + "-result",
                                ts=now,
                                actor="engine",
                                kind="notify_hook_result",
                                live=False,
                                payload_json={"attempt_id": hook_id},
                                result="completed",
                            )
                        )
            result["stages"].append("alerts")
        checkpoint("complete")
        return result
    except BaseException as exc:
        connection.rollback()
        result["error_kind"] = type(exc).__name__
        checkpoint("failed")
        raise


def database_backups(connection):
    return Path(connection.execute("PRAGMA database_list").fetchone()[2]).parent / "backups"


def status(connection, *, limit: int = 30) -> list[dict]:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limite deve ser 1–1000")
    return [
        {"id": row[0], "status": row[1], "payload": json.loads(row[2])}
        for row in connection.execute(
            "SELECT id,status,payload FROM scheduler_runs ORDER BY id DESC LIMIT ?", (limit,)
        )
    ]


def once(connection, *, now=None, root=Path("."), **kwargs) -> dict:
    """Retoma tentativas duráveis; nunca avalia slots que o host perdeu."""
    from arb.quarantine import require_released

    require_released(connection)
    now = now or datetime.now(UTC)
    if now.utcoffset() is None or connection.in_transaction:
        raise ValueError("once exige fuso e commit anterior")
    settings = Settings.model_validate(yaml.safe_load((root / "config/settings.yaml").read_text()))
    today = now.astimezone(ZONE).date()
    latest = max(
        s
        for s in schedule(today - timedelta(days=1), today, cycles=tuple(settings.cycles))
        if s <= now
    )
    latest_key = latest.astimezone(UTC).isoformat()
    old = connection.execute(
        "SELECT id FROM scheduler_runs WHERE status IN ('running','failed') ORDER BY id"
    ).fetchall()
    resumed = []
    for (key,) in old:
        slot = datetime.fromisoformat(key)
        if slot <= now:
            resumed.append(run_cycle(connection, slot, now=now, root=root, **kwargs))
    first = connection.execute("SELECT min(id) FROM scheduler_runs").fetchone()[0]
    # Bootstrap explicitly covers yesterday; later invocations use persisted history.
    start = (
        datetime.fromisoformat(first).astimezone(ZONE).date()
        if first
        else today - timedelta(days=1)
    )
    skipped = []
    while start <= today:
        end = min(start + timedelta(days=366), today)
        for slot in schedule(start, end, cycles=tuple(settings.cycles)):
            key = slot.astimezone(UTC).isoformat()
            if key >= latest_key or (first and key < first):
                continue
            payload = {
                "id": key,
                "stages": [],
                "alerts": ["missed_cycle: host indisponível; slot não executado"],
                "reason": "missed_cycle",
            }
            with connection:
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO scheduler_runs VALUES(?,?,?,?)",
                    (key, now.isoformat(), "skipped", json.dumps(payload, sort_keys=True)),
                )
                if inserted.rowcount:
                    skipped.append(key)
                    Repository(connection, Action).add(
                        Action(
                            id="missed-cycle-" + key,
                            ts=now,
                            actor="engine",
                            kind="scheduler_skip",
                            payload_json=payload,
                            live=False,
                            result="skipped",
                        )
                    )
        start = end + timedelta(days=1)
    result = run_cycle(connection, latest, now=now, root=root, **kwargs)
    return {"resumed": resumed, "skipped": skipped, "latest": result}
