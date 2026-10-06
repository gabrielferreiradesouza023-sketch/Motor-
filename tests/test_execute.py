from datetime import UTC, datetime

import pytest
from test_plan import launch_fixture

from arb.db import Repository, connect, migrate
from arb.launcher import plan, plan_hash
from arb.launcher.approval import sign
from arb.launcher.execute import execute
from arb.models import Action, Angle, Approval, Creative, Entity, Offer


def setup_launch(tmp_path):
    connection = connect(tmp_path / "db.sqlite")
    migrate(connection)
    offer, angles, creatives = launch_fixture()
    with connection:
        Repository(connection, Offer).add(offer)
        for record in angles:
            Repository(connection, Angle).add(record)
        for record in creatives:
            Repository(connection, Creative).add(record)
    value = plan(
        offer,
        angles,
        creatives,
        geo="CO",
        daily_budget_cents=6000,
        destination_url="https://bridge.example.test/oferta",
    )
    directory = tmp_path / "approved"
    directory.mkdir()
    approval = Approval(
        id="human",
        plan_hash=plan_hash(value),
        kind="launch",
        summary="Aprovação sintética de teste",
        max_exposure_cents=6000,
        status="approved",
        decided_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    approval = sign(approval)
    (directory / "human.json").write_text(approval.model_dump_json())
    return connection, value, approval, directory


def test_execution_paused_idempotent_and_audited(tmp_path):
    conn, value, approval, directory = setup_launch(tmp_path)
    try:
        first = execute(conn, value, approval.id, approval_dir=directory, output=tmp_path / "out")
        assert (
            execute(conn, value, approval.id, approval_dir=directory, output=tmp_path / "out")
            == first
        )
        assert len(Repository(conn, Action).list()) == 1
        assert len(Repository(conn, Entity).list()) == 13
        assert all(e.status == "paused" for e in Repository(conn, Entity).list())
        assert first.live is False and first.result == "simulated"
        assert (tmp_path / "out" / f"{plan_hash(value)}.json").is_file()
    finally:
        conn.close()


@pytest.mark.parametrize("change", ["hash", "exposure", "pending", "kind", "date", "live", "stale"])
def test_execute_fail_closed(tmp_path, monkeypatch, change):
    conn, value, approval, directory = setup_launch(tmp_path)
    if change == "hash":
        approval.plan_hash = "0" * 64
    if change == "exposure":
        approval.max_exposure_cents = 5999
    if change == "pending":
        approval.status = "pending"
    if change == "kind":
        approval.kind = "activate"
    if change == "date":
        approval.decided_at = None
    if change == "live":
        monkeypatch.setenv("LIVE_MODE", "true")
    if change == "stale":
        offer = value.offer.model_copy(update={"status": "killed"})
        with conn:
            Repository(conn, Offer).update(offer)
    (directory / "human.json").write_text(approval.model_dump_json())
    try:
        with pytest.raises(ValueError):
            execute(conn, value, approval.id, approval_dir=directory, output=tmp_path / "out")
        assert not Repository(conn, Action).list()
        assert not Repository(conn, Entity).list()
    finally:
        conn.close()
