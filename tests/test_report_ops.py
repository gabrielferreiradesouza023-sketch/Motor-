import json
import os
from datetime import UTC, datetime, timedelta

from arb.analyst.report import generate_report, operational_status
from arb.db import Repository, backup_daily, connect, migrate
from arb.db.checkpoint import drill
from arb.models import Action, Approval

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def test_ops_panel_reference_and_no_sensitive_payloads(tmp_path):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    kinds = ("new_offer", "creative_set", "launch", "activate", "scale")
    with conn:
        for kind in kinds:
            Repository(conn, Approval).add(
                Approval(
                    id=kind,
                    kind=kind,
                    plan_hash="a" * 64,
                    summary="SECRET_SENTINEL",
                    max_exposure_cents=0,
                    status="pending",
                )
            )
        for identity, result, payload in (
            ("attempt", "intent", {"entity_id": "e", "secret": "SECRET_SENTINEL"}),
            ("uncertain", "uncertain", {"attempt_id": "attempt"}),
            ("closed", "reconciled_paused", {"attempt_id": "other"}),
        ):
            Repository(conn, Action).add(
                Action(
                    id=identity,
                    ts=NOW - timedelta(seconds=30),
                    actor="engine",
                    kind="pause",
                    result=result,
                    payload_json=payload,
                    live=False,
                )
            )
        conn.execute(
            "INSERT INTO restore_quarantine VALUES(?,?,?,?,NULL)",
            ("q", "SECRET_SENTINEL", "a" * 64, NOW.isoformat()),
        )
    backup = backup_daily(conn, tmp_path / "backups", day=NOW.date())
    os.utime(backup, (NOW.timestamp() - 3600, NOW.timestamp() - 3600))
    assert drill(tmp_path / "backups", now=NOW - timedelta(seconds=120))["status"] == "passed"
    state = operational_status(conn, now=NOW)
    assert state == {
        "pending": 1,
        "uncertain": 1,
        "orphans": 0,
        "uncertain_results": 1,
        "quarantine": True,
        "backup_age_seconds": 3600,
        "drill": {"status": "passed", "age_seconds": 120},
        "last_reconciliation": (NOW - timedelta(seconds=30)).isoformat(),
        "pending_approvals": dict.fromkeys(kinds, 1),
    }
    text = generate_report(conn, tmp_path / "report", now=NOW).read_text()
    assert "SECRET_SENTINEL" not in text and "<script" not in text
    assert "Estado operacional" in text and "aberta" in text and "3600" in text
    assert all(kind + ": 1" in text for kind in kinds)
    assert text.count('<p class="decision-question">') == 1
    assert 'name="viewport"' in text and "auto-fit" in text
    conn.close()


def test_missing_ops_evidence_is_displayed(tmp_path):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    state = operational_status(conn, now=NOW)
    assert state["pending"] == 0 and not state["quarantine"]
    assert state["backup_age_seconds"] is None and state["last_reconciliation"] is None
    assert state["drill"]["status"] == "failed"
    text = generate_report(conn, tmp_path / "report", now=NOW).read_text()
    assert "falho ou ausente" in text and "Nenhuma." in text
    conn.close()


def test_invalid_drill_payload_is_never_rendered(tmp_path):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    directory = tmp_path / "backups"
    directory.mkdir()
    (directory / "drill.json").write_text(
        json.dumps({"status": "<script>SECRET_SENTINEL</script>"})
    )
    text = generate_report(conn, tmp_path / "report", now=NOW).read_text()
    assert "SECRET_SENTINEL" not in text and "falho ou ausente" in text
    conn.close()
