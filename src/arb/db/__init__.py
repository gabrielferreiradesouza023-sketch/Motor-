"""Interface pública de persistência, migração e backup (sem integração externa)."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypeVar

from arb.models import (
    Action,
    Angle,
    AngleLearning,
    Approval,
    Creative,
    Decision,
    Entity,
    MetricAdjustment,
    MetricSnapshot,
    Model,
    Offer,
    SaleEvent,
)
from arb.permissions import private_directory, private_open, reject_links

MIGRATIONS = Path(__file__).parent / "migrations"
T = TypeVar("T", bound=Model)
# Nome de tabela, chave pública e colunas relacionais. Nunca interpolar entrada do usuário.
TABLES = {
    MetricAdjustment: ("metric_adjustments", ("id",), ("entity_id",)),
    AngleLearning: ("angle_library", ("id",), ("angle_id", "offer_id")),
    Offer: ("offers", ("id",), ()),
    Angle: ("angles", ("id",), ("offer_id",)),
    Creative: ("creatives", ("id",), ("angle_id",)),
    Entity: ("entities", ("id",), ("parent_id", "offer_id", "angle_id", "creative_id")),
    MetricSnapshot: ("metric_snapshots", ("entity_id", "ts"), ()),
    SaleEvent: ("sale_events", ("id",), ("hotmart_tx_id", "matched_entity_id")),
    Decision: ("decisions", ("id",), ("entity_id",)),
    Approval: ("approvals", ("id",), ()),
    Action: ("actions", ("id",), ("approval_id",)),
}
APPEND_ONLY = (MetricSnapshot, MetricAdjustment, Decision, Action)


def connect(path: Path) -> sqlite3.Connection:
    with private_open(path, append=True):
        pass
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def migration_catalog() -> dict[int, tuple[str, str]]:
    return {
        int(path.name.split("_")[0]): (
            path.read_text(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(MIGRATIONS.glob("[0-9]*_*.sql"))
    }


def require_current_schema(connection: sqlite3.Connection) -> None:
    """Validate the same applied migration numbers/checksums in every local diagnostic."""
    applied = dict(connection.execute("SELECT version, checksum FROM schema_migrations"))
    expected = {number: data[1] for number, data in migration_catalog().items()}
    if applied != expected:
        raise ValueError("migrações")


def migrate(connection: sqlite3.Connection) -> None:
    """Migrações atômicas com checksum; não aceitam alteração de SQL já aplicado."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)"
    )
    connection.commit()
    applied = dict(connection.execute("SELECT version, checksum FROM schema_migrations"))
    catalog = migration_catalog()
    if any(
        version not in catalog or catalog[version][1] != sha for version, sha in applied.items()
    ):
        raise ValueError("migração desconhecida ou checksum divergente")
    for version, (sql, sha) in catalog.items():
        if version in applied:
            continue
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + sql
                + f"\nINSERT INTO schema_migrations VALUES ({version}, '{sha}');\nCOMMIT;"
            )
        except Exception:
            connection.rollback()
            raise


class Repository[T: Model]:
    """CRUD validado; inserções não duplicam chaves; logs são append-only.

    O chamador controla a transação via `with connection:`. Nenhum commit oculto.
    Snapshot usa chave (entity_id, ts); demais modelos usam id.
    """

    def __init__(self, connection: sqlite3.Connection, model: type[T]):
        self.connection = connection
        self.model = model
        self.table, self.keys, self.references = TABLES[model]

    def add(self, record: T) -> None:
        record = self.model.model_validate(record.model_dump())
        columns = (*self.keys, *self.references, "payload")
        data = record.model_dump(mode="json")
        values = [data[col] if col != "payload" else record.model_dump_json() for col in columns]
        placeholders = ",".join("?" for _ in columns)
        self.connection.execute(
            f"INSERT INTO {self.table} ({','.join(columns)}) VALUES ({placeholders})", values
        )

    def get(self, *key: str) -> T | None:
        if len(key) != len(self.keys):
            raise ValueError("chave inválida")
        where = " AND ".join(f"{column}=?" for column in self.keys)
        row = self.connection.execute(
            f"SELECT payload FROM {self.table} WHERE {where}", key
        ).fetchone()
        return self.model.model_validate_json(row[0]) if row else None

    def list(self) -> list[T]:
        rows = self.connection.execute(
            f"SELECT payload FROM {self.table} ORDER BY {','.join(self.keys)}"
        )
        return [self.model.model_validate_json(row[0]) for row in rows]

    def update(self, record: T) -> None:
        if self.model in APPEND_ONLY:
            raise ValueError("repositório append-only")
        record = self.model.model_validate(record.model_dump())
        data = record.model_dump(mode="json")
        sets = [f"{column}=?" for column in self.references] + ["payload=?"]
        where = " AND ".join(f"{column}=?" for column in self.keys)
        values = [data[column] for column in self.references] + [record.model_dump_json()]
        values.extend(data[column] for column in self.keys)
        cursor = self.connection.execute(
            f"UPDATE {self.table} SET {','.join(sets)} WHERE {where}", values
        )
        if cursor.rowcount != 1:
            raise KeyError("registro não encontrado")


def backup_daily(connection: sqlite3.Connection, directory: Path, day: date | None = None) -> Path:
    """Uma cópia por dia UTC, sete dias retidos; backup consistente e validado."""
    if connection.in_transaction:
        raise ValueError("commit necessário antes do backup")
    private_directory(directory)
    directory = directory.resolve()
    day = day or datetime.now(UTC).date()
    target = directory / f"engine-{day.isoformat()}.db"
    reject_links(target)
    if target.exists():
        with closing(sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True)) as existing:
            if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup diário existente inválido")
        return target
    temporary = target.with_suffix(".tmp")
    with private_open(temporary, exclusive=True):
        pass
    try:
        with closing(sqlite3.connect(temporary)) as destination:
            connection.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup inválido")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    backups = sorted(directory.glob("engine-????-??-??.db"))
    for old in backups[:-7]:
        old.unlink()
    return target
