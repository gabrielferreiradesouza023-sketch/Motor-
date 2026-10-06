from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from arb.analyst import pnl
from arb.db import Repository, connect, migrate
from arb.meta.read import MetaReadError, Reader
from arb.meta.sync import last_collection, sync
from arb.models import Action, Entity, MetricAdjustment, MetricSnapshot


@pytest.fixture
def database(tmp_path, records):
    connection = connect(tmp_path / "meta.db")
    migrate(connection)
    with connection:
        for record in records[:3]:
            Repository(connection, type(record)).add(record)
    yield connection
    connection.close()


def reader(*, spend="10.00", impressions="1000", status="PAUSED", fail=False):
    ad = {
        "id": "3",
        "status": status,
        "adset": {
            "id": "2",
            "status": "PAUSED",
            "daily_budget": "1000",
            "campaign": {"id": "1", "status": "PAUSED"},
        },
    }
    insight = {
        "ad_id": "3",
        "date_start": "2026-10-01",
        "date_stop": "2026-10-01",
        "impressions": impressions,
        "inline_link_clicks": "10",
        "spend": spend,
        "actions": [],
    }

    def respond(request):
        assert request.method == "GET"
        if request.url.path.endswith("/ads"):
            return httpx.Response(200, json={"data": [ad]})
        if request.url.path.endswith("/insights"):
            if fail:
                return httpx.Response(400, json={"error": {"code": 190}})
            return httpx.Response(200, json={"data": [insight]})
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    return Reader(
        "synthetic",
        "123",
        "v99.0",
        client=httpx.Client(transport=httpx.MockTransport(respond)),
        sleep=lambda _: None,
    )


def run(database, source, now=None, mapping=None):
    return sync(
        database,
        source,
        date(2026, 10, 1),
        date(2026, 10, 1),
        mapping=mapping if mapping is not None else {"3": {"offer_id": "offer", "geo": "CO"}},
        now=now or datetime(2026, 10, 2, 12, tzinfo=UTC),
    )


def test_sync_repeated_manual_change_and_negative_correction(database):
    assert run(database, reader())["snapshots"] == 1
    assert run(database, reader())["snapshots"] == 0
    assert len(Repository(database, MetricSnapshot).list()) == 1
    assert len(Repository(database, Action).list()) == 3
    changed = run(database, reader(spend="12.00", status="ACTIVE"))
    assert changed["snapshots"] == 1 and changed["entities_changed"] == 1
    assert Repository(database, Entity).get("meta-3").status == "active"
    assert all(a.actor == "human" and not a.live for a in Repository(database, Action).list())
    reduced = run(database, reader(spend="9.00", impressions="900"))
    assert reduced["adjustments"] == 1
    assert len(Repository(database, MetricAdjustment).list()) == 1
    report = pnl(database)
    assert report["totals"]["spend_platform_cents"] == 900
    assert report["totals"]["impressions"] == 900
    assert report["groups"]["daily"][0]["key"] == "2026-10-01"
    assert report["groups"]["daily"][0]["spend_platform_cents"] == 900
    with pytest.raises(ValueError, match="append-only"):
        Repository(database, MetricAdjustment).update(
            Repository(database, MetricAdjustment).list()[0]
        )


def test_failure_rolls_back_and_marks_collection_unsafe(database):
    first = datetime(2026, 10, 2, 12, tzinfo=UTC)
    run(database, reader(), now=first)
    assert last_collection(database) == first
    with pytest.raises(MetaReadError, match="incompleta"):
        run(database, reader(fail=True), now=first + timedelta(hours=1))
    assert last_collection(database) is None
    assert len(Repository(database, MetricSnapshot).list()) == 1
    assert (
        database.execute("SELECT status FROM meta_sync_runs ORDER BY ts DESC LIMIT 1").fetchone()[0]
        == "failed"
    )


def test_unknown_ad_mapping_and_invalid_last_row_rollback(database):
    with pytest.raises(MetaReadError):
        run(database, reader(), mapping={})
    assert not Repository(database, Entity).list()
    with pytest.raises(MetaReadError):
        run(database, reader(impressions="bad"))
    assert not Repository(database, Entity).list()
    assert not Repository(database, Action).list()
    assert not Repository(database, MetricSnapshot).list()
