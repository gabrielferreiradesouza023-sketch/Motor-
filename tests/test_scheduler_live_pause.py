from datetime import date

import httpx
import pytest
from test_scheduler import ROOT, seeded

from arb.db import Repository
from arb.meta.pause import PauseWriter
from arb.models import Action, Entity, MetricSnapshot
from arb.scheduler import run_cycle, schedule


@pytest.mark.parametrize("signal", ["stale", "kill", "cap", "brake"])
def test_live_signals_pause_once(tmp_path, records, monkeypatch, signal):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    entity = Repository(conn, Entity).get("entity")
    with conn:
        entity.meta_id = "123"
        Repository(conn, Entity).update(entity)
        if signal != "stale":
            Repository(conn, MetricSnapshot).add(
                records[4].model_copy(
                    update={
                        "ts": slot,
                        "period_start": slot.date(),
                        "impressions": 2000,
                        "link_clicks": 0,
                        "spend_platform_cents": 60000 if signal == "brake" else 4000,
                    }
                )
            )
    monkeypatch.setenv("LIVE_MODE", "true")
    seen = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(200, json={"success": True})
        )
    ) as client:
        writer = PauseWriter("synthetic", "v99.0", client)
        result = run_cycle(
            conn,
            slot,
            now=slot,
            root=ROOT,
            output=tmp_path / "reports",
            writer=writer,
            sync_source=(lambda c, n: n) if signal != "stale" else None,
        )
        assert len(seen) == 1 and seen[0].content == b"status=PAUSED"
        assert Repository(conn, Entity).get("entity").status == "paused"
        assert (
            run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "reports", writer=writer)
            == result
        )
        assert len(seen) == 1
    conn.close()


def test_partial_failure_and_pending_no_retry(tmp_path, records, monkeypatch):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    with conn:
        base = Repository(conn, Entity).get("entity")
        base.meta_id = "123"
        Repository(conn, Entity).update(base)
        Repository(conn, Entity).add(base.model_copy(update={"id": "second", "meta_id": "124"}))
    monkeypatch.setenv("LIVE_MODE", "true")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            503 if request.url.path.endswith("123") else 200, json={"success": True}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        writer = PauseWriter("synthetic", "v99.0", client)
        result = run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "out", writer=writer)
        assert len(seen) == 2
        assert Repository(conn, Entity).get("second").status == "paused"
        assert any("reconciliar" in a for a in result["alerts"])
        next_slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[1]
        result = run_cycle(
            conn, next_slot, now=next_slot, root=ROOT, output=tmp_path / "out", writer=writer
        )
        assert len(seen) == 2
        assert any("reconciliar" in a for a in result["alerts"])
    conn.close()


def test_parent_before_child_and_no_duplicate_child(tmp_path, records, monkeypatch):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    with conn:
        base = Repository(conn, Entity).get("entity")
        base.meta_id = "123"
        base.kind = "campaign"
        Repository(conn, Entity).update(base)
        Repository(conn, Entity).add(
            base.model_copy(
                update={"id": "child", "kind": "adset", "meta_id": "124", "parent_id": base.id}
            )
        )
    monkeypatch.setenv("LIVE_MODE", "true")
    seen = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: seen.append(r) or httpx.Response(200, json={"success": True})
        )
    ) as client:
        run_cycle(
            conn,
            slot,
            now=slot,
            root=ROOT,
            output=tmp_path / "out",
            writer=PauseWriter("synthetic", "v99.0", client),
        )
        assert len(seen) == 1 and seen[0].url.path.endswith("123")
        assert sum(a.result == "intent" for a in Repository(conn, Action).list()) == 1
    conn.close()


def test_simulation_remote_status_unchanged(tmp_path, records):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    with conn:
        base = Repository(conn, Entity).get("entity")
        base.meta_id = "123"
        Repository(conn, Entity).update(base)
    result = run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "out")
    assert result["pauses"] == []
    assert "remote_pause_pending: intervenção humana na Meta necessária" in result["alerts"]
    assert Repository(conn, Entity).get("entity").status == "active"
    conn.close()
