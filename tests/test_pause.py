from datetime import UTC, datetime

import pytest
from test_execute import setup_launch

from arb.db import Repository
from arb.launcher.actions import activate, activation_intent, automatic, intent_hash, pause
from arb.launcher.approval import sign
from arb.launcher.execute import execute
from arb.models import Action, Approval, Entity


def test_activation_separate_approval_pause_idempotent(tmp_path):
    conn, value, approval, directory = setup_launch(tmp_path)
    try:
        execute(conn, value, approval.id, approval_dir=directory, output=tmp_path / "out")
        entity = value.entities[0]
        with pytest.raises(ValueError):
            activate(conn, entity.id, approval.id, approval_dir=directory)
        activation = Approval(
            id="activate-human",
            plan_hash=intent_hash(activation_intent(entity)),
            kind="activate",
            summary="Fixture local",
            max_exposure_cents=6000,
            status="approved",
            decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        activation = sign(activation)
        (directory / "activate-human.json").write_text(activation.model_dump_json())
        action = activate(conn, entity.id, activation.id, approval_dir=directory)
        assert activate(conn, entity.id, activation.id, approval_dir=directory) == action
        assert pause(conn, entity.id, reason="freio") is not None
        assert pause(conn, entity.id, reason="freio") is None
        # Aprovação consumida não reativa depois de uma pausa.
        activate(conn, entity.id, activation.id, approval_dir=directory)
        assert Repository(conn, Entity).get(entity.id).status == "paused"
        assert len(Repository(conn, Action).list()) == 3
    finally:
        conn.close()


@pytest.mark.parametrize("kind", ["activate", "launch", "scale", "delete"])
def test_only_pause_is_automatic(tmp_path, kind):
    conn, _, _, _ = setup_launch(tmp_path)
    try:
        with pytest.raises(ValueError, match="somente pausa"):
            automatic(conn, kind, "anything", reason="reason")
        assert not Repository(conn, Action).list()
    finally:
        conn.close()


def test_remote_state_not_falsified(tmp_path):
    conn, value, approval, directory = setup_launch(tmp_path)
    try:
        execute(conn, value, approval.id, approval_dir=directory, output=tmp_path / "out")
        entity = value.entities[0].model_copy(
            update={"meta_id": "real-observed", "status": "active"}
        )
        with conn:
            Repository(conn, Entity).update(entity)
        with pytest.raises(ValueError, match="pausa real pendente"):
            pause(conn, entity.id, reason="panic")
        assert Repository(conn, Entity).get(entity.id).status == "active"
    finally:
        conn.close()
