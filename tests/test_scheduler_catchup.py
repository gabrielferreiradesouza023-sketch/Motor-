import json
from datetime import date, timedelta

import pytest
from test_scheduler import ROOT, seeded

from arb.db import Repository
from arb.models import Action
from arb.scheduler import once, run_cycle, schedule, status


@pytest.mark.parametrize("state", ["failed", "running"])
def test_old_incomplete_resumes_first_without_duplicate(tmp_path, records, state):
    conn = seeded(tmp_path, records)
    slots = schedule(date(2026, 10, 5), date(2026, 10, 7))
    result = run_cycle(conn, slots[0], now=slots[0], root=ROOT, output=tmp_path / "reports")
    with conn:
        conn.execute(
            "UPDATE scheduler_runs SET status=?,payload=? WHERE id=?",
            (state, json.dumps(result), result["id"]),
        )
    before = Repository(conn, Action).list()
    out = once(conn, now=slots[-1], root=ROOT, output=tmp_path / "reports")
    assert out["resumed"][0]["id"] == result["id"]
    assert len(out["skipped"]) == 7
    assert len(status(conn)) == 9
    assert sum(a.kind == "pause" for a in Repository(conn, Action).list()) == sum(
        a.kind == "pause" for a in before
    )
    count = len(Repository(conn, Action).list())
    assert once(conn, now=slots[-1], root=ROOT, output=tmp_path / "reports")["skipped"] == []
    assert len(Repository(conn, Action).list()) == count
    conn.close()


def test_two_days_off_only_latest_executes_and_slots_alert(tmp_path, records):
    conn = seeded(tmp_path, records)
    slots = schedule(date(2026, 10, 5), date(2026, 10, 7))
    run_cycle(conn, slots[0], now=slots[0], root=ROOT, output=tmp_path / "reports")
    calls = []
    result = once(
        conn,
        now=slots[-1],
        root=ROOT,
        output=tmp_path / "reports",
        sync_source=lambda db, now: calls.append(now),
    )
    assert calls == [slots[-1]]
    assert len(result["skipped"]) == 7
    assert all(row["payload"]["alerts"] for row in status(conn) if row["status"] == "skipped")
    conn.close()


@pytest.mark.parametrize("delta,expected", [(-1, "18:00"), (0, "23:30"), (1, "23:30")])
def test_slot_boundary(tmp_path, records, delta, expected):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[-1]
    result = once(conn, now=slot + timedelta(seconds=delta), root=ROOT, output=tmp_path / "reports")
    from datetime import datetime

    from arb.scheduler import ZONE

    assert (
        datetime.fromisoformat(result["latest"]["id"]).astimezone(ZONE).strftime("%H:%M")
        == expected
    )
    conn.close()


def test_real_failed_stage_resumes_before_current(tmp_path, records):
    conn = seeded(tmp_path, records)
    slots = schedule(date(2026, 10, 5), date(2026, 10, 7))

    def crash(*args, **kwargs):
        raise OSError("planted report failure")

    with pytest.raises(OSError):
        run_cycle(conn, slots[0], now=slots[0], root=ROOT, report_fn=crash)
    out = once(conn, now=slots[-1], root=ROOT, output=tmp_path / "reports")
    assert out["resumed"][0]["stages"] == ["sync", "rules", "actions", "report", "alerts"]
    assert out["resumed"][0]["id"] < out["latest"]["id"]
    assert sum(a.kind == "pause" for a in Repository(conn, Action).list()) == 1
    conn.close()


@pytest.mark.parametrize("limit", [0, 1001])
def test_status_refuses_invalid_limit(tmp_path, records, limit):
    conn = seeded(tmp_path, records)
    with pytest.raises(ValueError, match="limite"):
        status(conn, limit=limit)
    conn.close()
