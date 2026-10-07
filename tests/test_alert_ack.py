import json
from datetime import UTC, datetime

import pytest
from test_preflight import configured as _configured
from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.models import Action
from arb.preflight import inspect
from arb.scheduler.alerts import acknowledge, uncertain

configured = _configured
NOW = datetime(2026, 10, 7, tzinfo=UTC)


def seed(conn, *, kind="notification", messages=None, outcome=None):
    action = Action(
        id="uncertain-alert",
        ts=NOW,
        actor="engine",
        kind=kind,
        result="uncertain",
        live=False,
        payload_json={"cycle_id": "cycle", "messages": messages or ["stale: financial sentinel"]},
    )
    with conn:
        Repository(conn, Action).add(action)
        if kind == "notify_hook":
            conn.execute(
                "INSERT INTO scheduler_runs VALUES(?,?,?,?)",
                (
                    "cycle",
                    NOW.isoformat(),
                    "failed",
                    json.dumps({"alerts": messages or ["stale: financial sentinel"]}),
                ),
            )
        if outcome:
            Repository(conn, Action).add(
                action.model_copy(
                    update={
                        "id": "result",
                        "kind": kind + "_result",
                        "payload_json": {"attempt_id": action.id},
                        "result": outcome,
                    }
                )
            )
    return action


@pytest.mark.parametrize("kind", ["notification", "notify_hook"])
def test_uncertain_ack_idempotent_no_delivery(tmp_path, monkeypatch, kind):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    action = seed(conn, kind=kind)
    assert uncertain(conn) == [
        {"id": action.id, "kind": kind, "codes": ["stale"], "critical": True}
    ]
    import arb.launcher.approval as approval

    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    before = len(Repository(conn, Action).list())
    ack = acknowledge(conn, action.id, now=NOW)
    assert ack.actor == "human" and ack.result == "acknowledged"
    assert acknowledge(conn, action.id, now=NOW) == ack
    assert len(Repository(conn, Action).list()) == before + 1
    assert uncertain(conn) == []
    conn.close()


def test_no_tty_unknown_and_transaction_refused(tmp_path, monkeypatch):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    seed(conn)
    with pytest.raises(ValueError, match="tty"):
        acknowledge(conn, "uncertain-alert")
    import arb.launcher.approval as approval

    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    with pytest.raises(ValueError, match="não encontrado"):
        acknowledge(conn, "unknown")
    conn.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        acknowledge(conn, "uncertain-alert")
    conn.rollback()
    conn.close()


@pytest.mark.parametrize("outcome", ["sent", "completed"])
def test_confirmed_delivery_not_uncertain(tmp_path, outcome):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    seed(conn, outcome=outcome)
    assert uncertain(conn) == []
    conn.close()


def test_preflight_blocks_critical_until_ack(configured, monkeypatch):
    root, database, _ = configured
    conn = connect(database)
    seed(conn)
    result = inspect(root=root, database=database, now=NOW)
    check = next(c for c in result["checks"] if c["name"] == "alert_ack")
    assert check["status"] == "erro" and "sem ack: 1; críticos: 1" in check["message"]
    import arb.launcher.approval as approval

    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    acknowledge(conn, "uncertain-alert")
    result = inspect(root=root, database=database, now=NOW)
    assert next(c for c in result["checks"] if c["name"] == "alert_ack")["status"] == "ok"
    conn.close()


def test_engine_cannot_forge_ack_and_payloads_hidden(tmp_path, monkeypatch):
    conn = connect(tmp_path / "engine.db")
    migrate(conn)
    action = seed(conn, messages=["approval_pending: token=synthetic-hidden"])
    with conn:
        Repository(conn, Action).add(
            action.model_copy(
                update={
                    "id": "alert-ack-" + action.id,
                    "kind": "alert_ack",
                    "payload_json": {"alert_id": action.id},
                    "result": "acknowledged",
                }
            )
        )
    assert uncertain(conn)[0]["critical"] is False
    assert "synthetic-hidden" not in json.dumps(uncertain(conn))
    import arb.launcher.approval as approval

    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    with pytest.raises(ValueError, match="conflito"):
        acknowledge(conn, action.id)
    conn.close()


def test_missing_hook_cycle_fails_closed_and_cli(tmp_path):
    path = tmp_path / "engine.db"
    conn = connect(path)
    migrate(conn)
    seed(conn, kind="notify_hook")
    with conn:
        conn.execute("DELETE FROM scheduler_runs")
    assert uncertain(conn)[0]["codes"] == ["unknown"]
    conn.close()
    result = CliRunner().invoke(app, ["ops", "alerts", "--database", str(path), "--json"])
    assert result.exit_code == 0 and json.loads(result.stdout)[0]["critical"]
    result = CliRunner().invoke(app, ["ops", "ack", "uncertain-alert", "--database", str(path)])
    assert result.exit_code == 1 and "tty" in result.stdout
