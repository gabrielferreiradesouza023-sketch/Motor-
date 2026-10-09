"""Local observations only; intervals are uncertainty, not invented winner segments."""

import json
import math
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from arb.config import Rules, Settings
from arb.db import Repository
from arb.metrics import spend_gross
from arb.models import Entity, MetricAdjustment, MetricSnapshot, SaleEvent
from arb.permissions import private_open, reject_links
from arb.tracker import entity_map
from arb.tracker.sync import decode_event

Z90 = 1.6448536269514722


def window(since: str, until: str, *, timezone: str = "UTC") -> tuple[datetime, datetime]:
    def parse(value, end=False):
        if len(value) == 10:
            day = date.fromisoformat(value)
            return datetime.combine(
                day + timedelta(days=int(end)), time(), ZoneInfo(timezone)
            ).astimezone(UTC)
        value = datetime.fromisoformat(value)
        if value.utcoffset() is None:
            raise ValueError("janela exige fuso")
        return value.astimezone(UTC)

    first, last = parse(since), parse(until, True)
    if first >= last:
        raise ValueError("janela invertida ou vazia")
    return first, last


def wilson(successes: int, count: int) -> tuple[float, float]:
    if count <= 0 or not 0 <= successes <= count:
        raise ValueError("contagem binomial inválida")
    p = successes / count
    divisor = 1 + Z90**2 / count
    center = (p + Z90**2 / (2 * count)) / divisor
    half = Z90 * math.sqrt(p * (1 - p) / count + Z90**2 / (4 * count**2)) / divisor
    return max(0.0, center - half), min(1.0, center + half)


def profile(
    connection: sqlite3.Connection, since: str, until: str, *, rules: Rules, settings: Settings
) -> dict:
    first, last = window(since, until, timezone=settings.timezone)
    entities = {e.id: e for e in Repository(connection, Entity).list()}
    tests = {row[0] for row in connection.execute("SELECT entity_id FROM acceptance_test_entities")}
    entities = {key: value for key, value in entities.items() if key not in tests}
    aliases = entity_map(connection)
    snapshots = Repository(connection, MetricSnapshot).list()
    adjustments = Repository(connection, MetricAdjustment).list()
    sales = Repository(connection, SaleEvent).list()
    receipts = []
    seen = {}
    for (payload,) in connection.execute("SELECT payload FROM tracker_receipts ORDER BY source,id"):
        event, marked = decode_event(json.loads(payload))
        identifier = aliases.get(event.ad_id)
        if not marked and identifier in entities and first <= event.ts < last:
            if event.id in seen and seen[event.id] != event:
                raise ValueError("recibo de ponte conflitante")
            if event.id not in seen:
                receipts.append((identifier, event))
                seen[event.id] = event
    fields = (
        "impressions",
        "video_3s_views",
        "link_clicks",
        "spend_platform_cents",
        "bridge_views",
        "checkout_clicks",
    )
    rows = {}

    def period(ts, day):
        return (
            datetime.combine(day, time(), ZoneInfo(settings.timezone)).astimezone(UTC)
            if day
            else ts
        )

    for geo in sorted({e.geo for e in entities.values()}):
        ids = {key for key, e in entities.items() if e.geo == geo}
        items = [
            s
            for s in snapshots
            if s.entity_id in ids and first <= period(s.ts, s.period_start) < last
        ]
        corrections = [
            a
            for a in adjustments
            if a.entity_id in ids and first <= period(a.ts, a.period_start) < last
        ]
        counts = {
            f: sum(getattr(s, f) for s in items) + sum(a.deltas.get(f, 0) for a in corrections)
            for f in fields
        }
        events = [e for identifier, e in receipts if identifier in ids]
        if events:
            counts["bridge_views"] = sum(e.kind == "view" for e in events)
            counts["checkout_clicks"] = sum(e.kind == "checkout_click" for e in events)
        matched = [
            s
            for s in sales
            if s.matched_entity_id in ids and first <= s.ts < last and s.status == "approved"
        ]
        sample = counts | {"sales": len(matched)}
        reasons = []
        if counts["impressions"] < rules.gate_1.min_impressions:
            reasons.append("min_impressions")
        if counts["bridge_views"] < rules.gate_2.min_bridge_views:
            reasons.append("min_bridge_views")
        if len(matched) < rules.gate_3.min_sales:
            reasons.append("min_sales")
        pairs = {
            "ctr": (counts["link_clicks"], counts["impressions"]),
            "hook": (counts["video_3s_views"], counts["impressions"]),
            "checkout": (counts["checkout_clicks"], counts["bridge_views"]),
            "purchase": (len(matched), counts["checkout_clicks"]),
        }
        if (
            any(n <= 0 or not 0 <= k <= n for k, n in pairs.values())
            or counts["spend_platform_cents"] <= 0
        ):
            reasons.append("invalid_or_empty_counters")
        if reasons:
            rows[geo] = {"status": "insufficient_data", "samples": sample, "reasons": reasons}
            continue
        impressions = counts["impressions"]
        raw_cpm = counts["spend_platform_cents"] * 1000 / impressions
        if raw_cpm < 1:
            rows[geo] = {
                "status": "insufficient_data",
                "samples": sample,
                "reasons": ["subcent_cpm"],
            }
            continue
        # Conditional Poisson impression-count approximation, not Wilson for currency.
        error = Z90 / math.sqrt(impressions)
        if error >= 1:
            rows[geo] = {
                "status": "insufficient_data",
                "samples": sample,
                "reasons": ["poisson_interval_unresolved"],
            }
            continue
        cpm_interval = [max(1, math.floor(raw_cpm / (1 + error))), math.ceil(raw_cpm / (1 - error))]
        rates = {
            key: {"estimate": k / n, "interval90": list(wilson(k, n)), "n": n, "successes": k}
            for key, (k, n) in pairs.items()
        }
        distribution = {
            "cpm_cents": cpm_interval,
            **{key: value["interval90"] for key, value in rates.items()},
        }
        rows[geo] = {
            "status": "sufficient",
            "samples": sample,
            "rates": rates,
            "cpm_gross_cents": spend_gross(counts["spend_platform_cents"], settings.media_tax_rate)
            * 1000
            / impressions,
            "cpm_gross_interval90_cents": [
                spend_gross(v, settings.media_tax_rate) for v in cpm_interval
            ],
            "bridge_source": "receipts" if events else "snapshot_counters",
            "distribution": distribution,
        }
    return {
        "origin": "local_sqlite",
        "window": {"since": first.isoformat(), "until_exclusive": last.isoformat()},
        "confidence": 0.9,
        "geos": rows,
        "limitations": [
            "Taxas de janela, não coorte: atrasos de vendas afetam a conversão.",
            "CPM bruto usa imposto configurado; V-04/fatura não é inferida.",
            "CPM usa aproximação Poisson condicional de impressões; taxas usam Wilson 90%.",
            "Papéis compartilham a mesma distribuição observada; nenhum vencedor é inventado.",
            "Comissão/refund/orçamento continuam as hipóteses existentes do laboratório, "
            "não fatos novos.",
        ],
    }


def write_profile(result: dict, output: Path) -> Path:
    reject_links(output)
    if "config" in output.absolute().parts:
        raise ValueError("perfil observado não pode escrever em config")
    body = {}
    for geo, row in result["geos"].items():
        if row["status"] == "sufficient":
            body["observed_" + geo] = {
                role: dict(row["distribution"])
                for role in ("winner", "borderline_winner", "attention_trap", "loser")
            }
        else:
            body["observed_" + geo] = {
                "status": "insufficient_data",
                "samples": row["samples"],
                "reasons": row["reasons"],
            }
    if not body:
        body = {"observed": {"status": "insufficient_data"}}
    metadata = {
        **result,
        "geos": {
            geo: {k: v for k, v in row.items() if k != "distribution"}
            for geo, row in result["geos"].items()
        },
    }
    header = "# OBSERVED: local database only; no market values fabricated.\n"
    header += "# " + json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n"
    with private_open(output) as file:
        file.write(header + yaml.safe_dump(body, sort_keys=True, allow_unicode=True))
    return output
