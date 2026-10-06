from datetime import timedelta

import httpx
import pytest

from arb.db import Repository, connect, migrate
from arb.models import Entity, MetricSnapshot, SaleEvent
from arb.tracker import import_sales, match
from arb.tracker.sync import sync


@pytest.fixture
def tracking_db(tmp_path, records):
    connection = connect(tmp_path / "tracker.db")
    migrate(connection)
    with connection:
        for record in records[:4]:
            Repository(connection, type(record)).add(record)
    yield connection
    connection.close()


def test_csv_dedup_refund_unmatched_and_header(tracking_db, tmp_path, records):
    path = tmp_path / "sales.csv"
    header = "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
    line = "tx1,2026-10-05T12:00:00Z,5000,approved,entity\n"
    path.write_text(header + line + line)
    assert import_sales(tracking_db, path) == 1
    assert import_sales(tracking_db, path) == 0
    sale = Repository(tracking_db, SaleEvent).list()[0]
    assert sale.matched_entity_id == "entity"
    path.write_text(header + line.replace("approved", "refunded"))
    assert import_sales(tracking_db, path) == 1
    path.write_text(header + line)
    assert import_sales(tracking_db, path) == 0
    assert Repository(tracking_db, SaleEvent).list()[0].status == "refunded"
    path.write_text(header + line.replace("tx1", "tx2").replace("entity", "unknown"))
    assert import_sales(tracking_db, path) == 1
    entity = records[3].model_copy(update={"id": "new", "meta_id": "unknown"})
    with tracking_db:
        Repository(tracking_db, Entity).add(entity)
    assert match(tracking_db) == 1
    path.write_text("wrong,header\n")
    with pytest.raises(ValueError, match="Cabeçalho"):
        import_sales(tracking_db, path)


def test_conflicting_csv_rolls_back(tracking_db, tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
        "tx1,2026-10-05T12:00:00Z,5000,approved,entity\n"
        "tx1,2026-10-05T12:00:00Z,6000,approved,entity\n"
    )
    with pytest.raises(ValueError, match="divergente"):
        import_sales(tracking_db, path)
    assert not Repository(tracking_db, SaleEvent).list()


def test_paginated_sync_collision_replay_and_resume(tracking_db, records):
    ts = records[4].ts.isoformat()
    events = [
        {"cursor": n, "id": f"event-{n}", "kind": kind, "ad_id": "entity", "geo": "CO", "ts": ts}
        for n, kind in [(1, "view"), (2, "checkout_click")]
    ]
    sale = records[5].model_dump(mode="json") | {"cursor": 1, "matched_entity_id": None}

    def respond(request):
        cursor = int(request.url.params["after_event"])
        assert request.headers["Authorization"].startswith("Bearer ")
        if cursor == 0:
            return httpx.Response(200, json={"events": events[:1], "sales": [], "more": True})
        if cursor == 1:
            return httpx.Response(200, json={"events": events[1:], "sales": [sale], "more": False})
        return httpx.Response(200, json={"events": [], "sales": [], "more": False})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = sync(tracking_db, "https://worker.example", "synthetic", client=client)
        assert result == {"events": 2, "sales": 1}
        assert sync(tracking_db, "https://worker.example", "synthetic", client=client) == {
            "events": 0,
            "sales": 0,
        }
    snapshots = sorted(Repository(tracking_db, MetricSnapshot).list(), key=lambda s: s.ts)
    assert len(snapshots) == 2
    assert snapshots[1].ts - snapshots[0].ts == timedelta(microseconds=1)
    assert sum(s.bridge_views for s in snapshots) == 1
    assert sum(s.checkout_clicks for s in snapshots) == 1
    assert Repository(tracking_db, SaleEvent).list()[0].matched_entity_id == "entity"


def test_invalid_page_does_not_advance_cursor(tracking_db):
    def respond(request):
        return httpx.Response(
            200, json={"events": [{"cursor": 1, "id": "bad"}], "sales": [], "more": False}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError):
            sync(tracking_db, "https://worker.example", "synthetic", client=client)
    assert not tracking_db.execute("SELECT * FROM tracker_cursors").fetchall()
    assert not Repository(tracking_db, MetricSnapshot).list()


def test_failed_second_page_resumes_from_last_committed_cursor(tracking_db):
    event = {
        "cursor": 1,
        "id": "resume-event",
        "kind": "view",
        "ad_id": "entity",
        "geo": "CO",
        "ts": "2026-10-05T12:00:00Z",
    }

    def fail_after_first(request):
        if request.url.params["after_event"] == "0":
            return httpx.Response(200, json={"events": [event], "sales": [], "more": True})
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(fail_after_first)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            sync(tracking_db, "https://worker.example", "synthetic", client=client)
    assert tracking_db.execute("SELECT event_cursor FROM tracker_cursors").fetchone()[0] == 1
    assert len(Repository(tracking_db, MetricSnapshot).list()) == 1

    def resume(request):
        assert request.url.params["after_event"] == "1"
        return httpx.Response(200, json={"events": [], "sales": [], "more": False})

    with httpx.Client(transport=httpx.MockTransport(resume)) as client:
        assert sync(tracking_db, "https://worker.example", "synthetic", client=client) == {
            "events": 0,
            "sales": 0,
        }
