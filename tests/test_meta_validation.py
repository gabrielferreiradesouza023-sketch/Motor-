"""Planted malformed provider responses must leave no partial money observations."""

from datetime import UTC, date, datetime

import httpx
import pytest

from arb.db import Repository, connect, migrate
from arb.meta.read import MetaReadError, Reader
from arb.meta.sync import sync
from arb.models import Action, Entity, MetricSnapshot


@pytest.mark.parametrize(
    "violation",
    [
        "duplicate_ad",
        "unknown_offer",
        "invalid_id",
        "conflict",
        "period",
        "duplicate_insight",
        "unknown_insight",
        "negative",
        "naive",
    ],
)
def test_sync_violations_roll_back_complete_observation(tmp_path, records, violation):
    conn = connect(tmp_path / "synthetic.db")
    migrate(conn)
    with conn:
        for record in records[:3]:
            Repository(conn, type(record)).add(record)
    ads = [
        {
            "id": "3",
            "status": "ACTIVE",
            "adset": {"id": "2", "status": "ACTIVE", "campaign": {"id": "1", "status": "ACTIVE"}},
        }
    ]
    insights = [
        {"ad_id": "3", "date_start": "2026-10-01", "date_stop": "2026-10-01", "spend": "10.00"}
    ]
    mapping = {"3": {"offer_id": "offer", "geo": "CO"}}
    now = datetime(2026, 10, 2, tzinfo=UTC)
    if violation == "duplicate_ad":
        ads *= 2
    elif violation == "unknown_offer":
        mapping["3"]["offer_id"] = "absent"
    elif violation == "invalid_id":
        ads[0]["adset"]["id"] = "../secret"
    elif violation == "conflict":
        with conn:
            Repository(conn, Entity).add(
                Entity(
                    id="existing",
                    meta_id="2",
                    kind="ad",
                    offer_id="offer",
                    geo="CO",
                    gate="0",
                    daily_budget_cents=0,
                    status="paused",
                )
            )
    elif violation == "period":
        insights[0]["date_stop"] = "2026-10-02"
    elif violation == "duplicate_insight":
        insights *= 2
    elif violation == "unknown_insight":
        insights[0]["ad_id"] = "99"
    elif violation == "negative":
        insights[0]["spend"] = "-1.00"
    else:
        now = now.replace(tzinfo=None)
    original_entities = Repository(conn, Entity).list()

    def respond(req):
        assert req.method == "GET"
        if req.url.path.endswith("/ads"):
            return httpx.Response(200, json={"data": ads})
        if req.url.path.endswith("/insights"):
            return httpx.Response(200, json={"data": insights})
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = Reader("synthetic", "123", "v99.0", client=client)
        with pytest.raises((MetaReadError, ValueError)):
            sync(conn, reader, date(2026, 10, 1), date(2026, 10, 1), mapping=mapping, now=now)
    assert Repository(conn, Entity).list() == original_entities
    assert Repository(conn, Action).list() == []
    assert Repository(conn, MetricSnapshot).list() == []
    conn.close()


@pytest.mark.parametrize("body", [[], {"data": "invalid"}, {"error": "invalid"}, None])
def test_reader_rejects_malformed_body_without_echo(body):
    def respond(req):
        return (
            httpx.Response(200, json=body)
            if body is not None
            else httpx.Response(200, text="SYNTHETIC_PRIVATE_BODY")
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = Reader("synthetic", "123", "v99.0", client=client)
        with pytest.raises(MetaReadError) as exc:
            reader.ads()
        assert "SYNTHETIC_PRIVATE_BODY" not in str(exc.value)


def test_reader_backoff_throttle_and_invalid_paths():
    calls, sleeps = [], []

    def respond(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(500, headers={"Retry-After": "bad"})
        if len(calls) == 2:
            return httpx.Response(
                200,
                json={"data": []},
                headers={"X-App-Usage": '{"call_count": 90}', "X-Ad-Account-Usage": "bad"},
            )
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader = Reader("synthetic", "123", "v99.0", client=client, sleep=sleeps.append)
        assert reader.ads() == [] and reader.ads() == []
        assert sleeps == [1, 5]
        with pytest.raises(ValueError):
            reader.get("../unsafe", {})
        with pytest.raises(ValueError):
            reader.insights(date(2026, 10, 2), date(2026, 10, 1))
        with pytest.raises(ValueError):
            Reader("synthetic", "123", "v99.0", client=client, attempts=0)
        assert len(calls) == 3
