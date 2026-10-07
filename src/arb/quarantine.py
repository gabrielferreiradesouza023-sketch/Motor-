"""Restore só volta a operar após pausa, leitura e confirmação interativa."""

from datetime import UTC, datetime

import typer

from arb.db import Repository
from arb.launcher.approval import is_interactive
from arb.ledger import pending
from arb.models import Action, Entity
from arb.reconcile import observed_statuses


def current(connection) -> dict | None:
    row = connection.execute(
        "SELECT id,backup_origin,backup_sha256,restored_at FROM restore_quarantine "
        "WHERE released_at IS NULL ORDER BY restored_at,id LIMIT 1"
    ).fetchone()
    return (
        dict(zip(("id", "backup_origin", "backup_sha256", "restored_at"), row, strict=True))
        if row
        else None
    )


def require_released(connection) -> None:
    if current(connection):
        raise ValueError("restore em quarentena: pausar, reconciliar e executar arb db release")


def release(connection, *, reader=None, confirm=None, now=None) -> Action | None:
    if connection.in_transaction:
        raise ValueError("liberação requer commit anterior")
    marker = current(connection)
    if marker is None:
        return None
    if not is_interactive():
        raise ValueError("liberação exige tty humano")
    if pending(connection):
        raise ValueError("reconciliar pendências antes de liberar")
    entities = Repository(connection, Entity).list()
    if any(e.status == "active" and e.meta_id is None for e in entities):
        raise ValueError("entidade local ativa: executar panic antes de liberar")
    remote = [e for e in entities if e.meta_id is not None]
    if remote:
        if reader is None:
            raise ValueError("entidades remotas exigem leitura de verificação")
        statuses = observed_statuses(reader)
        if any(statuses.get(e.meta_id) != "PAUSED" for e in remote):
            raise ValueError("estado remoto não confirmado PAUSED; preservar quarentena")
    confirm = confirm or (lambda: typer.confirm("Liberar banco restaurado verificado e pausado?"))
    if not confirm():
        raise ValueError("liberação cancelada pelo humano")
    now = now or datetime.now(UTC)
    connection.execute("BEGIN IMMEDIATE")
    try:
        if current(connection) != marker or pending(connection):
            raise ValueError("estado alterado durante liberação; revisar novamente")
        if Repository(connection, Entity).list() != entities:
            raise ValueError("entidades alteradas durante liberação")
        action = Action(
            id="restore-release-" + marker["id"],
            ts=now,
            actor="human",
            kind="restore_release",
            payload_json={"quarantine_id": marker["id"], "backup_sha256": marker["backup_sha256"]},
            live=False,
            result="released",
        )
        Repository(connection, Action).add(action)
        connection.execute(
            "UPDATE restore_quarantine SET released_at=? WHERE id=?",
            (now.isoformat(), marker["id"]),
        )
        connection.commit()
        return action
    except BaseException:
        connection.rollback()
        raise
