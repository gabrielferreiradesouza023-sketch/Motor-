import fcntl
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from arb.db import Repository, connect, migrate
from arb.models import Action, Decision, Entity, MetricSnapshot, Offer
from arb.scheduler import run_cycle, schedule

ROOT = Path(__file__).resolve().parents[1]


def seeded(tmp_path, records):
    conn = connect(tmp_path / "scheduler.db")
    migrate(conn)
    with conn:
        Repository(conn, Offer).add(records[0])
        Repository(conn, Entity).add(
            records[3].model_copy(
                update={"creative_id": None, "angle_id": None, "status": "active"}
            )
        )
    return conn


def test_three_days_nine_cycles_idempotent_and_order(tmp_path, records):
    conn = seeded(tmp_path, records)
    slots = schedule(date(2026, 10, 5), date(2026, 10, 7))
    assert len(slots) == 9
    assert [slot.astimezone(UTC).strftime("%H:%M") for slot in slots[:3]] == [
        "12:00",
        "21:00",
        "02:30",
    ]
    calls = []

    def source(db, now):
        calls.append(now)
        with db:
            Repository(db, MetricSnapshot).add(
                records[4].model_copy(update={"ts": now, "link_clicks": 0})
            )
        return now

    try:
        for slot in slots:
            result = run_cycle(
                conn, slot, now=slot, sync_source=source, root=ROOT, output=tmp_path / "reports"
            )
            assert result["stages"] == ["sync", "rules", "actions", "report", "alerts"]
            assert (
                run_cycle(
                    conn, slot, now=slot, sync_source=source, root=ROOT, output=tmp_path / "reports"
                )
                == result
            )
        assert len(calls) == 9
        assert conn.execute("SELECT count(*) FROM scheduler_runs").fetchone()[0] == 9
        assert len(Repository(conn, Action).list()) == 1
        assert len(Repository(conn, Decision).list()) == 1
        assert Repository(conn, Entity).get("entity").status == "paused"
        assert len(list((tmp_path / "backups").glob("*.db"))) == 4  # 23:30 SP cruza dia UTC
    finally:
        conn.close()


def test_report_failure_resumes_without_duplicate_protection(tmp_path, records):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 5), date(2026, 10, 5))[0]

    def broken(*args, **kwargs):
        raise OSError("fixture failure")

    try:
        with pytest.raises(OSError):
            run_cycle(
                conn, slot, now=slot, root=ROOT, output=tmp_path / "reports", report_fn=broken
            )
        assert Repository(conn, Entity).get("entity").status == "paused"
        result = run_cycle(conn, slot, now=slot, root=ROOT, output=tmp_path / "reports")
        assert len(Repository(conn, Action).list()) == 1
        assert any("stale" in alert for alert in result["alerts"])
    finally:
        conn.close()


def test_sync_and_notification_failure_still_pause(tmp_path, records):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 5), date(2026, 10, 5))[0]

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic")

    try:
        result = run_cycle(
            conn,
            slot,
            now=slot,
            root=ROOT,
            output=tmp_path / "reports",
            sync_source=broken,
            notify=broken,
        )
        assert Repository(conn, Entity).get("entity").status == "paused"
        assert any("sync_failed" in a for a in result["alerts"])
        assert any("notification_failed" in a for a in result["alerts"])
    finally:
        conn.close()


def test_time_and_concurrent_cycle_rejected(tmp_path, records):
    conn = seeded(tmp_path, records)
    slot = schedule(date(2026, 10, 5), date(2026, 10, 5))[0]
    try:
        with pytest.raises(ValueError):
            run_cycle(conn, slot, now=datetime(2026, 10, 1, tzinfo=UTC), root=ROOT)
        with (tmp_path / "scheduler.db.scheduler.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(ValueError, match="outro ciclo"):
                run_cycle(conn, slot, now=slot, root=ROOT)
    finally:
        conn.close()
