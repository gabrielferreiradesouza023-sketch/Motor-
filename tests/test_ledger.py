from datetime import UTC, datetime

import httpx
import pytest
from test_execute import setup_launch
from typer.testing import CliRunner

from arb import safety
from arb.cli import app
from arb.db import Repository
from arb.launcher.actions import pause
from arb.launcher.execute import execute
from arb.ledger import pending, require_clear
from arb.meta.pause import PauseWriter
from arb.models import Action, Entity

NOW = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit, httpx.ReadTimeout])
def test_crash_pending_and_no_second_post(tmp_path, monkeypatch, failure):
    conn, plan, approval, directory = setup_launch(tmp_path)
    execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
    entity = plan.entities[1].model_copy(update={"meta_id": "123", "status": "active"})
    with conn:
        Repository(conn, Entity).update(entity)
    monkeypatch.setattr(safety, "live_mode", lambda: True)
    calls = []

    def handler(request):
        calls.append(request)
        raise failure("synthetic crash")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        writer = PauseWriter("synthetic", "v99.0", client)
        with pytest.raises((failure, ValueError)):
            pause(conn, entity.id, reason="kill", writer=writer, now=NOW)
        assert len(calls) == 1
        row = pending(conn, now=NOW)[0]
        assert row == {
            "attempt_id": row["attempt_id"],
            "entity_id": entity.id,
            "meta_id": "123",
            "kind": "pause",
            "age_seconds": 0,
            "state": "uncertain" if failure is httpx.ReadTimeout else "orphan",
        }
        before = Repository(conn, Action).list()
        with pytest.raises(ValueError, match="reconciliar antes"):
            pause(conn, entity.id, reason="retry", writer=writer)
        assert Repository(conn, Action).list() == before and len(calls) == 1
    with conn:
        Repository(conn, Action).add(
            Action(
                id=row["attempt_id"] + "-reconciled",
                ts=NOW,
                actor="engine",
                kind="pause_result",
                payload_json={"attempt_id": row["attempt_id"]},
                live=False,
                result="reconciled_not_paused",
            )
        )
    assert pending(conn) == []
    require_clear(conn, entity.id)
    conn.close()


def test_cli_json_empty(tmp_path):
    result = CliRunner().invoke(
        app, ["ops", "pending", "--database", str(tmp_path / "db"), "--json"]
    )
    assert result.exit_code == 0 and result.stdout.strip() == "[]"
