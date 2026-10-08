"""Consome exportação paginada do Worker, atomicamente por página."""

import json
import sqlite3
from datetime import timedelta
from urllib.parse import urlsplit

import httpx

from arb.db import Repository
from arb.models import BridgeEvent, MetricSnapshot, SaleEvent
from arb.tracker import entity_map, ingest, match


def decode_event(body):
    raw = dict(body)
    marked = "test" in raw
    if marked and raw.pop("test") is not True:
        raise ValueError("marcação de teste inválida")
    if "event_id" in raw:
        nonce = raw.pop("event_id")
        if nonce != raw.get("id") or raw.get("kind") != "checkout_click":
            raise ValueError("event_id de checkout inválido")
    return BridgeEvent.model_validate(raw), marked


def apply_receipts(connection: sqlite3.Connection) -> int:
    aliases = entity_map(connection)
    count = 0
    repository = Repository(connection, MetricSnapshot)
    for source, identifier, payload in connection.execute(
        "SELECT source,id,payload FROM tracker_receipts WHERE applied=0 ORDER BY source,id"
    ).fetchall():
        event, marked = decode_event(json.loads(payload))
        if marked:
            connection.execute(
                "UPDATE tracker_receipts SET applied=1 WHERE source=? AND id=?",
                (source, identifier),
            )
            continue  # Recibo auditável, nunca MetricSnapshot nem P&L.
        entity_id = aliases.get(event.ad_id)
        if entity_id is None:
            continue
        timestamp = event.ts
        while repository.get(entity_id, timestamp.isoformat().replace("+00:00", "Z")):
            timestamp += timedelta(microseconds=1)
        repository.add(
            MetricSnapshot(
                entity_id=entity_id,
                ts=timestamp,
                impressions=0,
                video_3s_views=0,
                link_clicks=0,
                spend_platform_cents=0,
                bridge_views=int(event.kind == "view"),
                checkout_clicks=int(event.kind == "checkout_click"),
            )
        )
        connection.execute(
            "UPDATE tracker_receipts SET applied=1 WHERE source=? AND id=?", (source, identifier)
        )
        count += 1
    return count


def sync(
    connection: sqlite3.Connection,
    worker_url: str,
    token: str,
    *,
    client: httpx.Client | None = None,
) -> dict:
    url = urlsplit(worker_url)
    if (
        not token
        or (
            url.scheme != "https"
            and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1"))
        )
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Worker URL/token inválidos")
    source = worker_url.rstrip("/")
    owned = client is None
    client = client or httpx.Client(timeout=30)
    totals = {"events": 0, "sales": 0}
    try:
        for _ in range(10000):
            row = connection.execute(
                "SELECT event_cursor,sale_cursor FROM tracker_cursors WHERE source=?", (source,)
            ).fetchone() or (0, 0)
            response = client.get(
                source + "/export",
                params={"after_event": row[0], "after_sale": row[1]},
                headers={"Authorization": "Bearer " + token},
            )
            response.raise_for_status()
            document = response.json()
            if set(document) != {"events", "sales", "more"} or not isinstance(
                document["more"], bool
            ):
                raise ValueError("Exportação inválida")
            events = []
            sales = []
            cursors = list(row)
            for index, stream in enumerate(["events", "sales"]):
                for item in document[stream]:
                    body = dict(item)
                    cursor = body.pop("cursor")
                    if type(cursor) is not int or cursor <= cursors[index]:
                        raise ValueError("Cursor não avança")
                    cursors[index] = cursor
                    (events if index == 0 else sales).append(
                        decode_event(body) if index == 0 else SaleEvent.model_validate(body)
                    )
            if document["more"] and cursors == list(row):
                raise ValueError("Exportação sem avanço")
            with connection:
                for event, marked in events:
                    payload = event.model_dump_json()
                    if marked:
                        payload = json.dumps(event.model_dump(mode="json") | {"test": True})
                    previous = connection.execute(
                        "SELECT payload FROM tracker_receipts WHERE source=? AND id=?",
                        (source, event.id),
                    ).fetchone()
                    if previous and json.loads(previous[0]) != json.loads(payload):
                        raise ValueError("Evento repetido divergente")
                    connection.execute(
                        "INSERT OR IGNORE INTO tracker_receipts(source,id,payload) VALUES (?,?,?)",
                        (source, event.id, payload),
                    )
                totals["events"] += apply_receipts(connection)
                for sale in sales:
                    totals["sales"] += ingest(connection, sale)
                connection.execute(
                    "INSERT INTO tracker_cursors VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET "
                    "event_cursor=MAX(tracker_cursors.event_cursor,excluded.event_cursor),"
                    "sale_cursor=MAX(tracker_cursors.sale_cursor,excluded.sale_cursor)",
                    (source, *cursors),
                )
            if not document["more"]:
                break
        else:
            raise ValueError("Paginação excedeu o limite")
    finally:
        if owned:
            client.close()
    match(connection)
    return totals
