from datetime import date

import pytest
from test_execute import setup_launch
from test_scheduler import ROOT

from arb.db import Repository, backup_daily, connect, migrate, migration_catalog
from arb.db.restore import restore_new
from arb.launcher.actions import activate
from arb.launcher.execute import execute
from arb.launcher.panic import panic
from arb.models import Action, Entity
from arb.quarantine import current, release
from arb.scheduler import run_cycle, schedule


def restored_launch(tmp_path):
    conn, plan, approval, directory = setup_launch(tmp_path)
    execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
    with conn:
        e = plan.entities[1].model_copy(update={"status": "active"})
        Repository(conn, Entity).update(e)
    snapshot = backup_daily(conn, tmp_path / "backups")
    panic(conn)
    assert Repository(conn, Entity).get(e.id).status == "paused"
    target = restore_new(snapshot, tmp_path / "restored.db")
    conn.close()
    recovered = connect(target)
    return recovered, plan, approval, directory


def test_restore_blocks_operations_but_panic_allows_release(tmp_path, monkeypatch):
    conn, plan, approval, directory = restored_launch(tmp_path)
    assert current(conn)["backup_sha256"] and len(current(conn)["backup_sha256"]) == 64
    slot = schedule(date(2026, 10, 7), date(2026, 10, 7))[0]
    for operation in (
        lambda: execute(conn, plan, approval.id, approval_dir=directory),
        lambda: activate(conn, plan.entities[1].id, "no-approval"),
        lambda: run_cycle(conn, slot, now=slot, root=ROOT),
    ):
        with pytest.raises(ValueError, match="quarentena"):
            operation()
    with pytest.raises(ValueError, match="tty"):
        release(conn)
    import arb.quarantine as module

    monkeypatch.setattr(module, "is_interactive", lambda: True)
    with pytest.raises(ValueError, match="ativa"):
        release(conn, confirm=lambda: True)
    panic(conn)
    with pytest.raises(ValueError, match="cancelada"):
        release(conn, confirm=lambda: False)
    monkeypatch.setattr(module.typer, "confirm", lambda _: True)
    action = release(conn)
    assert action.actor == "human" and action.kind == "restore_release"
    assert current(conn) is None and release(conn) is None
    conn.close()


@pytest.mark.parametrize("status", ["PAUSED", "ACTIVE", "UNKNOWN", None])
def test_remote_release_requires_reading(tmp_path, monkeypatch, status):
    import arb.quarantine as module

    conn, plan, _, _ = restored_launch(tmp_path)
    monkeypatch.setattr(module, "is_interactive", lambda: True)
    panic(conn)
    with conn:
        entity = Repository(conn, Entity).get(plan.entities[1].id)
        entity.meta_id = "123"
        Repository(conn, Entity).update(entity)
    with pytest.raises(ValueError, match="leitura"):
        release(conn, confirm=lambda: True)

    class Source:
        def ads(self):
            return [{"id": "123", "status": status}]

    if status == "PAUSED":
        assert release(conn, reader=Source(), confirm=lambda: True)
    else:
        with pytest.raises(ValueError, match="PAUSED"):
            release(conn, reader=Source(), confirm=lambda: True)
        assert current(conn)
    conn.close()


def test_pending_and_confirmation_race_refused(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    import arb.quarantine as module

    conn, plan, _, _ = restored_launch(tmp_path)
    monkeypatch.setattr(module, "is_interactive", lambda: True)
    panic(conn)
    intent = Action(
        id="orphan",
        ts=datetime.now(UTC),
        actor="engine",
        kind="pause",
        payload_json={"entity_id": plan.entities[1].id},
        live=False,
        result="intent",
    )
    with conn:
        Repository(conn, Action).add(intent)
    with pytest.raises(ValueError, match="pendências"):
        release(conn, confirm=lambda: True)
    with conn:
        Repository(conn, Action).add(
            intent.model_copy(
                update={
                    "id": "closed",
                    "kind": "pause_result",
                    "payload_json": {"attempt_id": "orphan"},
                    "result": "reconciled_paused",
                }
            )
        )

    def modify():
        with conn:
            entity = Repository(conn, Entity).get(plan.entities[1].id)
            entity.status = "active"
            Repository(conn, Entity).update(entity)
        return True

    with pytest.raises(ValueError, match="entidades alteradas"):
        release(conn, confirm=modify)
    assert current(conn) and not conn.in_transaction
    panic(conn)

    def new_pending():
        with conn:
            Repository(conn, Action).add(intent.model_copy(update={"id": "new"}))
        return True

    with pytest.raises(ValueError, match="estado alterado"):
        release(conn, confirm=new_pending)
    conn.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        release(conn)
    conn.rollback()
    conn.close()


def test_old_schema_upgrades_with_checksum(tmp_path):
    conn = connect(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
    )
    conn.commit()
    catalog = migration_catalog()
    for number, (sql, sha) in catalog.items():
        if number >= 6:
            continue
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations VALUES(?,?)", (number, sha))
        conn.commit()
    migrate(conn)
    assert dict(conn.execute("SELECT * FROM schema_migrations"))[6] == catalog[6][1]
    assert current(conn) is None
    conn.close()


@pytest.mark.parametrize("changes", [False, True])
def test_release_aligns_remote_or_rolls_back(tmp_path, monkeypatch, changes):
    import arb.quarantine as module

    conn, plan, _, _ = restored_launch(tmp_path)
    monkeypatch.setattr(module, "is_interactive", lambda: True)
    with conn:
        entity = Repository(conn, Entity).get(plan.entities[1].id)
        entity.meta_id = "123"
        Repository(conn, Entity).update(entity)

    class Source:
        calls = 0

        def ads(self):
            self.calls += 1
            return [{"id": "123", "status": "ACTIVE" if changes and self.calls > 1 else "PAUSED"}]

    before = Repository(conn, Action).list()
    if changes:
        with pytest.raises(ValueError, match="PAUSED"):
            release(conn, reader=Source(), confirm=lambda: True)
        assert current(conn)
        assert Repository(conn, Entity).get(entity.id).status == "active"
        assert Repository(conn, Action).list() == before
    else:
        release(conn, reader=Source(), confirm=lambda: True)
        assert Repository(conn, Entity).get(entity.id).status == "paused"
        actions = [a for a in Repository(conn, Action).list() if a.kind == "reconcile_restore"]
        assert len(actions) == 1
        assert actions[0].payload_json == {
            "entity_id": entity.id,
            "before": "active",
            "after": "paused",
            "observed": "PAUSED",
        }
    conn.close()
