import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_execute import setup_launch
from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.db.checkpoint import SNAPSHOT_RETENTION, backup_directory, drill, snapshot_before
from arb.launcher.actions import activate, activation_intent, intent_hash
from arb.launcher.approval import sign
from arb.launcher.execute import execute
from arb.models import Action, Approval, Entity


def test_snapshot_precedes_launch_and_activation(tmp_path):
    conn, plan, approval, directory = setup_launch(tmp_path)
    execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
    first = next(backup_directory(conn).glob("pre-launch-*.db"))
    with sqlite3.connect(first) as backup:
        assert Repository(backup, Entity).list() == []
        assert Repository(backup, Action).list() == []
    entity = plan.entities[1]
    identifier = approve_activation(entity, directory)
    activate(conn, entity.id, identifier, approval_dir=directory)
    second = next(backup_directory(conn).glob("pre-activate-*.db"))
    with sqlite3.connect(second) as backup:
        assert Repository(backup, Entity).get(entity.id).status == "paused"
        assert not any(a.kind == "activate" for a in Repository(backup, Action).list())
    before = Path(conn.execute("PRAGMA database_list").fetchone()[2]).read_bytes()
    report = drill(backup_directory(conn))
    assert report["status"] == "passed" and report["quarantined"]
    assert report["counts"]["Entity"] == len(plan.entities)
    assert before == Path(conn.execute("PRAGMA database_list").fetchone()[2]).read_bytes()
    assert not list(backup_directory(conn).glob("*.tmp"))
    conn.close()


@pytest.mark.parametrize("operation", ["launch", "activate"])
def test_failed_snapshot_prevents_exposure(tmp_path, monkeypatch, operation):
    import arb.db.checkpoint as module

    conn, plan, approval, directory = setup_launch(tmp_path)
    if operation == "activate":
        execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
    before = Repository(conn, Action).list()

    def broken(*args, **kwargs):
        raise OSError("synthetic disk full")

    monkeypatch.setattr(module, "snapshot_before", broken)
    with pytest.raises(OSError):
        if operation == "launch":
            execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
        else:
            identifier = approve_activation(plan.entities[1], directory)
            activate(conn, plan.entities[1].id, identifier, approval_dir=directory)
    assert Repository(conn, Action).list() == before
    assert all(e.status == "paused" for e in Repository(conn, Entity).list())
    conn.close()


def test_retention_repeat_and_validation(tmp_path):
    conn = connect(tmp_path / "database.db")
    migrate(conn)
    target = snapshot_before(conn, "scale", "first")
    original = target.read_bytes()
    assert snapshot_before(conn, "scale", "first").read_bytes() == original
    for i in range(SNAPSHOT_RETENTION + 1):
        snapshot_before(conn, "scale", str(i))
    assert len(list(backup_directory(conn).glob("pre-*.db"))) == SNAPSHOT_RETENTION
    assert not target.exists()
    conn.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        snapshot_before(conn, "scale", "transaction")
    conn.rollback()
    for kind, identifier in [("delete", "ok"), ("launch", "../bad")]:
        with pytest.raises(ValueError, match="inválida"):
            snapshot_before(conn, kind, identifier)
    with sqlite3.connect(":memory:") as memory:
        with pytest.raises(ValueError, match="arquivo"):
            backup_directory(memory)
    conn.close()


def test_corrupt_and_absent_drill_are_failures(tmp_path):
    assert drill(tmp_path)["status"] == "failed"
    (tmp_path / "corrupt.db").write_bytes(b"not sqlite")
    assert drill(tmp_path)["status"] == "failed"
    result = CliRunner().invoke(app, ["db", "drill", "--backups", str(tmp_path), "--json"])
    assert result.exit_code == 1 and '"status": "failed"' in result.stdout


def approve_activation(entity, directory):
    approval = sign(
        Approval(
            id="activation-human",
            kind="activate",
            summary="synthetic",
            plan_hash=intent_hash(activation_intent(entity)),
            max_exposure_cents=6000,
            status="approved",
            decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    (directory / (approval.id + ".json")).write_text(approval.model_dump_json())
    return approval.id


def test_snapshot_publication_race_preserves_first(tmp_path, monkeypatch):
    import shutil

    import arb.db.checkpoint as module

    conn = connect(tmp_path / "database.db")
    migrate(conn)

    def competing_publish(source, destination):
        shutil.copyfile(source, destination)
        raise FileExistsError("competing valid snapshot")

    monkeypatch.setattr(module.os, "link", competing_publish)
    target = snapshot_before(conn, "scale", "race")
    with sqlite3.connect(target) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not list(target.parent.glob("*.tmp"))
    target.write_bytes(b"corrupt")
    with pytest.raises(sqlite3.DatabaseError):
        snapshot_before(conn, "scale", "race")
    conn.close()
