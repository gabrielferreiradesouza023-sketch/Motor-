"""Reconciliação e deltas: transação só depois de todos os GETs completos."""

import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from arb.db import Repository
from arb.meta.read import MetaReadError, Reader
from arb.models import Action, Entity, MetricAdjustment, MetricSnapshot, Offer
from arb.tracker import match

COUNTERS = ("impressions", "video_3s_views", "link_clicks", "spend_platform_cents")


def integer(value) -> int:
    if not re.fullmatch(r"\d+", str(value)):
        raise ValueError("Contador inteiro inválido")
    return int(value)


def cents(value) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Gasto inválido")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def sync(
    connection: sqlite3.Connection,
    reader: Reader,
    since: date,
    until: date,
    *,
    mapping: dict[str, dict[str, str]] | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("Coleta exige fuso")
    mapping = mapping or {}
    run_id = str(uuid4())
    result = {"entities_changed": 0, "snapshots": 0, "adjustments": 0}
    source = reader.account_id
    try:
        reader.account()
        ads = reader.ads()
        insights = reader.insights(since, until)
        entities = {e.meta_id: e for e in Repository(connection, Entity).list() if e.meta_id}
        seen_ads = set()
        with connection:
            for ad in ads:
                identifier = str(ad["id"])
                if identifier in seen_ads:
                    raise ValueError("Anúncio duplicado na coleta")
                seen_ads.add(identifier)
                known = entities.get(identifier)
                assignment = mapping.get(identifier, {})
                offer_id = known.offer_id if known else assignment.get("offer_id")
                geo = known.geo if known else assignment.get("geo")
                if not geo or not re.fullmatch(r"[A-Z]{2}", geo):
                    raise ValueError("Anúncio desconhecido exige geo explícito no mapping")
                if not offer_id or not Repository(connection, Offer).get(offer_id):
                    raise ValueError("Anúncio desconhecido exige mapping ad_id→offer_id válido")
                adset = ad["adset"]
                campaign = adset["campaign"]
                parent = None
                for raw, kind in [(campaign, "campaign"), (adset, "adset"), (ad, "ad")]:
                    meta_id = str(raw["id"])
                    if not re.fullmatch(r"\d+", meta_id):
                        raise ValueError("Meta id inválido")
                    existing = entities.get(meta_id)
                    if existing and (existing.offer_id != offer_id or existing.kind != kind):
                        raise ValueError("Mapeamento de entidade conflitante")
                    active = raw.get("effective_status", raw["status"]) == "ACTIVE"
                    changes = {
                        "parent_id": parent,
                        "daily_budget_cents": integer(raw.get("daily_budget", 0)),
                        "status": "active" if active else "paused",
                    }
                    if existing:
                        # Ad não possui budget próprio; preservar contexto/budget local do ad.
                        if kind == "ad":
                            changes.pop("daily_budget_cents")
                        updated = existing.model_copy(update=changes)
                    else:
                        updated = Entity(
                            id="meta-" + meta_id,
                            kind=kind,
                            meta_id=meta_id,
                            offer_id=offer_id,
                            geo=geo,
                            gate="0",
                            **changes,
                        )
                    repo = Repository(connection, Entity)
                    if updated != existing:
                        repo.update(updated) if existing else repo.add(updated)
                        Repository(connection, Action).add(
                            Action(
                                id=str(uuid4()),
                                ts=now,
                                actor="human",
                                kind="manual_reconciliation",
                                live=False,
                                payload_json={
                                    "input": existing.model_dump(mode="json") if existing else None,
                                    "output": updated.model_dump(mode="json"),
                                },
                                result="observed_read_only",
                            )
                        )
                        result["entities_changed"] += 1
                    entities[meta_id] = updated
                    parent = updated.id
            seen = set()
            snapshots = Repository(connection, MetricSnapshot)
            for row in insights:
                identifier = str(row["ad_id"])
                period = date.fromisoformat(row["date_start"])
                if row["date_stop"] != row["date_start"] or not since <= period <= until:
                    raise ValueError("Período inválido")
                if (identifier, period) in seen:
                    raise ValueError("Insight diário duplicado")
                seen.add((identifier, period))
                entity = entities.get(identifier)
                if entity is None or entity.kind != "ad":
                    raise ValueError("Insight sem entidade reconciliada")
                current = {
                    "impressions": integer(row.get("impressions", 0)),
                    "video_3s_views": sum(
                        integer(a["value"])
                        for a in row.get("actions", [])
                        if a["action_type"] == "video_view"
                    ),
                    "link_clicks": integer(row.get("inline_link_clicks", 0)),
                    "spend_platform_cents": cents(row.get("spend", 0)),
                }
                previous = connection.execute(
                    "SELECT payload FROM meta_daily WHERE source=? AND ad_id=? AND period=?",
                    (source, identifier, period.isoformat()),
                ).fetchone()
                old = json.loads(previous[0]) if previous else dict.fromkeys(COUNTERS, 0)
                delta = {f: current[f] - old[f] for f in COUNTERS}
                if any(v > 0 for v in delta.values()):
                    timestamp = now
                    while snapshots.get(entity.id, timestamp.isoformat().replace("+00:00", "Z")):
                        timestamp += timedelta(microseconds=1)
                    snapshots.add(
                        MetricSnapshot(
                            entity_id=entity.id,
                            ts=timestamp,
                            period_start=period,
                            bridge_views=0,
                            checkout_clicks=0,
                            **{f: max(v, 0) for f, v in delta.items()},
                        )
                    )
                    result["snapshots"] += 1
                if any(v < 0 for v in delta.values()):
                    Repository(connection, MetricAdjustment).add(
                        MetricAdjustment(
                            id=str(uuid4()),
                            entity_id=entity.id,
                            ts=now,
                            period_start=period,
                            deltas={f: v for f, v in delta.items() if v < 0},
                            reason="Meta restated daily insight",
                        )
                    )
                    result["adjustments"] += 1
                connection.execute(
                    "INSERT INTO meta_daily VALUES (?,?,?,?) ON CONFLICT(source,ad_id,period) "
                    "DO UPDATE SET payload=excluded.payload",
                    (source, identifier, period.isoformat(), json.dumps(current)),
                )
            connection.execute(
                "INSERT INTO meta_sync_runs VALUES (?,?,?,NULL)",
                (run_id, now.isoformat(timespec="microseconds"), "complete"),
            )
    except (
        MetaReadError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        ArithmeticError,
        sqlite3.Error,
    ) as exc:
        with connection:
            connection.execute(
                "INSERT INTO meta_sync_runs VALUES (?,?,?,?)",
                (run_id, now.isoformat(timespec="microseconds"), "failed", type(exc).__name__),
            )
        raise MetaReadError("Coleta incompleta: nenhuma decisão de pass permitida") from None
    match(connection)
    return result


def last_collection(connection: sqlite3.Connection) -> datetime | None:
    row = connection.execute(
        "SELECT ts,status FROM meta_sync_runs ORDER BY ts DESC,rowid DESC LIMIT 1"
    ).fetchone()
    return datetime.fromisoformat(row[0]) if row and row[1] == "complete" else None
