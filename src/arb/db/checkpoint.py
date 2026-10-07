"""Snapshots pré-exposição (20 retidos) e ensaio em cópia descartável."""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from arb.db import TABLES, Repository
from arb.db.restore import restore_new

SNAPSHOT_RETENTION = 20


def backup_directory(connection) -> Path:
    database = connection.execute("PRAGMA database_list").fetchone()[2]
    if not database:
        raise ValueError("snapshot exige banco em arquivo")
    return Path(database).parent / "backups"


def snapshot_before(connection, kind: str, identifier: str) -> Path:
    if connection.in_transaction:
        raise ValueError("snapshot requer commit anterior")
    if kind not in {"launch", "activate", "scale"} or not re.fullmatch(
        r"[A-Za-z0-9_-]+", identifier
    ):
        raise ValueError("intenção de snapshot inválida")
    directory = backup_directory(connection)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"pre-{kind}-{identifier}.db"
    if not target.exists():
        with NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
        try:
            with closing(sqlite3.connect(temporary)) as destination:
                connection.backup(destination)
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass  # preserve o primeiro ponto de restauração, inclusive em corrida
        finally:
            temporary.unlink(missing_ok=True)
    with closing(sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True)) as saved:
        if saved.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("snapshot inválido")
    backups = sorted(directory.glob("pre-*.db"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    for old in backups[:-SNAPSHOT_RETENTION]:
        old.unlink()
    return target


def drill(directory: Path, *, now=None) -> dict:
    now = now or datetime.now(UTC)
    result = {"status": "failed", "checked_at": now.isoformat(), "counts": {}}
    directory.mkdir(parents=True, exist_ok=True)
    backups = sorted(directory.glob("*.db"), key=lambda p: (p.stat().st_mtime_ns, p.name))
    try:
        if not backups:
            raise ValueError("backup ausente")
        backup = backups[-1]
        result["backup"] = backup.name
        result["sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
        with TemporaryDirectory(prefix="arb-db-drill-") as temporary:
            recovered = restore_new(backup, Path(temporary) / "recovered.db")
            with closing(sqlite3.connect(recovered)) as connection:
                result["counts"] = {
                    model.__name__: len(Repository(connection, model).list()) for model in TABLES
                }
                result["quarantined"] = bool(
                    connection.execute(
                        "SELECT count(*) FROM restore_quarantine WHERE released_at IS NULL"
                    ).fetchone()[0]
                )
                result["status"] = "passed"
    except (ValueError, OSError, sqlite3.DatabaseError):
        result["error"] = "backup ausente, corrompido ou contratos inválidos"
    target = directory / "drill.json"
    with NamedTemporaryFile(mode="w", dir=directory, delete=False) as file:
        temporary = Path(file.name)
        json.dump(result, file, sort_keys=True)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return result
