"""P&L acumulado e por coorte, reconstruído da fonte SQLite."""

import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from arb.db import Repository
from arb.metrics import cost_per_learning, spend_gross, summarize, waste_ratio
from arb.models import Decision, Entity, MetricSnapshot, SaleEvent


def pnl(
    connection: sqlite3.Connection,
    *,
    media_tax_rate: float = 0.13,
    refund_rate: float = 0.15,
    total_cap_cents: int = 240000,
) -> dict:
    entities = {e.id: e for e in Repository(connection, Entity).list()}
    snapshots = Repository(connection, MetricSnapshot).list()
    sales = Repository(connection, SaleEvent).list()
    decisions = Repository(connection, Decision).list()
    fields = (
        "impressions",
        "video_3s_views",
        "link_clicks",
        "spend_platform_cents",
        "bridge_views",
        "checkout_clicks",
    )
    zones = ZoneInfo("America/Sao_Paulo")
    first_dates = {}
    for s in snapshots:
        d = s.ts.astimezone(zones).date().isoformat()
        first_dates[s.entity_id] = min(first_dates.get(s.entity_id, d), d)
    rows = {}
    for level in ("offer", "angle", "creative", "geo", "daily"):
        grouped = defaultdict(list)
        for s in snapshots:
            entity = entities[s.entity_id]
            key = (
                s.ts.astimezone(zones).date().isoformat()
                if level == "daily"
                else entity.geo
                if level == "geo"
                else getattr(entity, f"{level}_id")
            )
            if key:
                grouped[key].append(s)
        rows[level] = []
        for key, items in sorted(grouped.items()):
            ids = {s.entity_id for s in items}
            matched = [
                sale
                for sale in sales
                if sale.matched_entity_id in ids
                and (level != "daily" or first_dates.get(sale.matched_entity_id) == key)
            ]
            aggregate = MetricSnapshot(
                entity_id=str(key),
                ts=max(s.ts for s in items),
                **{f: sum(getattr(s, f) for s in items) for f in fields},
            )
            stats = summarize(
                aggregate, matched, media_tax_rate=media_tax_rate, refund_rate=refund_rate
            )
            latest_kill = [d for d in decisions if d.entity_id in ids and d.verdict == "kill"]
            stats.update(
                key=key,
                profit_cents=stats["rev_expected"] - stats["spend_gross"],
                reopened=bool(latest_kill and (stats["roi_expected"] or 0) > 0),
            )
            rows[level].append(stats)
    total = MetricSnapshot(
        entity_id="all",
        ts=max((s.ts for s in snapshots), default=datetime.now(UTC)),
        **{f: sum(getattr(s, f) for s in snapshots) for f in fields},
    )
    matched = [s for s in sales if s.matched_entity_id in entities]
    totals = summarize(total, matched, media_tax_rate=media_tax_rate, refund_rate=refund_rate)
    sampled = sum(
        d.verdict in ("kill", "pass") and d.metrics_json.get("sample_sufficient", False)
        for d in decisions
    )
    # União dos gastos após a primeira decisão de kill, mais overshoot no teto registrado.
    killed = {}
    cap_excess = 0
    for d in sorted(decisions, key=lambda d: d.ts):
        if d.verdict == "kill" and d.entity_id not in killed:
            killed[d.entity_id] = d.ts
            cap_excess += max(
                0,
                d.metrics_json.get("spend_gross", 0)
                - d.metrics_json.get("cap_cents", d.metrics_json.get("spend_gross", 0)),
            )
    late_platform = sum(
        s.spend_platform_cents
        for s in snapshots
        if any(
            s.ts > ts and (s.entity_id == eid or entities[s.entity_id].parent_id == eid)
            for eid, ts in killed.items()
        )
    )
    excess = cap_excess + spend_gross(late_platform, media_tax_rate)
    totals.update(
        profit_cents=totals["rev_expected"] - totals["spend_gross"],
        cash_remaining_cents=max(0, total_cap_cents - totals["spend_gross"]),
        waste_ratio=waste_ratio(excess, totals["spend_gross"]),
        cost_per_learning_cents=cost_per_learning(totals["spend_gross"], sampled),
    )
    return {
        "totals": totals,
        "groups": rows,
        "unmatched": [s.model_dump(mode="json") for s in sales if s.matched_entity_id is None],
        "decisions": [d.model_dump(mode="json") for d in decisions],
        "alerts": ["Receita é esperada e não reciclável; não é saldo disponível."],
    }
