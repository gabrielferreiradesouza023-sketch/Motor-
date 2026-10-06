import sqlite3
from datetime import date, timedelta

import pytest

from arb.db import Repository, backup_daily, connect, migrate
from arb.models import Action, Decision, MetricSnapshot, Offer, SaleEvent


@pytest.fixture
def database(tmp_path, records):
    connection = connect(tmp_path / "engine.db")
    migrate(connection)
    with connection:
        for record in records:
            Repository(connection, type(record)).add(record)
    yield connection
    connection.close()


@pytest.mark.parametrize("index", range(9))
def test_repository_round_trip(database, records, index):
    record = records[index]
    repo = Repository(database, type(record))
    data = record.model_dump(mode="json")
    assert repo.get(*(data[key] for key in repo.keys)) == record
    assert repo.list() == [record]
    assert repo.get(*("missing" for _ in repo.keys)) is None


def test_migrations_repeatable(database):
    before = database.execute("SELECT * FROM schema_migrations").fetchall()
    migrate(database)
    assert before == database.execute("SELECT * FROM schema_migrations").fetchall()
    assert database.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_altered_migration_refused(database):
    with database:
        database.execute("UPDATE schema_migrations SET checksum='bad'")
    with pytest.raises(ValueError, match="checksum"):
        migrate(database)


def test_failed_migration_is_atomic(tmp_path, monkeypatch):
    import arb.db as db

    connection = connect(tmp_path / "failed.db")
    monkeypatch.setattr(
        db,
        "migration_catalog",
        lambda: {
            1: ("CREATE TABLE incomplete(id TEXT); INSERT INTO nonexistent VALUES (1);", "a" * 64)
        },
    )
    with pytest.raises(sqlite3.OperationalError):
        migrate(connection)
    assert not connection.execute(
        "SELECT name FROM sqlite_master WHERE name='incomplete'"
    ).fetchall()
    assert not connection.execute("SELECT * FROM schema_migrations").fetchall()
    connection.close()


def test_sale_transaction_unique_and_update(database, records):
    repo = Repository(database, SaleEvent)
    sale = records[5].model_copy(update={"id": "duplicate"})
    with pytest.raises(sqlite3.IntegrityError), database:
        repo.add(sale)
    assert len(repo.list()) == 1
    refunded = records[5].model_copy(update={"status": "refunded"})
    with database:
        repo.update(refunded)
    assert repo.get("sale").status == "refunded"


def test_foreign_keys_and_transaction_rollback(database, records):
    with pytest.raises(sqlite3.IntegrityError), database:
        Repository(database, Offer).add(records[0].model_copy(update={"id": "new-offer"}))
        Repository(database, SaleEvent).add(
            records[5].model_copy(
                update={"id": "bad", "hotmart_tx_id": "tx2", "matched_entity_id": "missing"}
            )
        )
    assert Repository(database, Offer).get("new-offer") is None


@pytest.mark.parametrize(
    "model,table",
    [(MetricSnapshot, "metric_snapshots"), (Decision, "decisions"), (Action, "actions")],
)
def test_append_only_at_repository_and_sql_level(database, model, table):
    repo = Repository(database, model)
    with pytest.raises(ValueError, match="append-only"):
        repo.update(repo.list()[0])
    for sql in [f"UPDATE {table} SET payload=payload", f"DELETE FROM {table}"]:
        with pytest.raises(sqlite3.IntegrityError), database:
            database.execute(sql)


def test_backup_rotation_repeat_and_restore(database, tmp_path, records):
    directory = tmp_path / "backups"
    day = date(2026, 10, 1)
    target = backup_daily(database, directory, day)
    first = target.read_bytes()
    assert backup_daily(database, directory, day).read_bytes() == first
    for offset in range(1, 9):
        target = backup_daily(database, directory, day + timedelta(days=offset))
    assert len(list(directory.glob("*.db"))) == 7
    assert not (directory / "engine-2026-10-01.db").exists()
    restored = connect(target)
    migrate(restored)
    for record in records:
        assert Repository(restored, type(record)).list() == [record]
    restored.close()


def test_backup_uncommitted_refused(database, tmp_path):
    database.execute("UPDATE offers SET payload=payload")
    with pytest.raises(ValueError, match="commit"):
        backup_daily(database, tmp_path / "backups")
    database.rollback()


def test_corrupt_existing_backup_refused(database, tmp_path):
    target = tmp_path / "engine-2026-10-05.db"
    target.write_bytes(b"not sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        backup_daily(database, tmp_path, date(2026, 10, 5))
