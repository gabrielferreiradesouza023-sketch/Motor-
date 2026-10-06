"""Freio local honesto: nenhuma entidade remota é anunciada como pausada."""

import sqlite3

from arb.db import Repository
from arb.launcher.actions import pause
from arb.launcher.execute import require_simulation
from arb.models import Entity


def panic(connection: sqlite3.Connection) -> dict:
    require_simulation()
    result = {
        "mode": "simulation",
        "paused_local": 0,
        "already_paused": 0,
        "remote_pause_pending": [],
        "errors": [],
    }
    for entity in Repository(connection, Entity).list():
        if entity.status == "paused":
            result["already_paused"] += 1
        elif entity.meta_id is not None:
            result["remote_pause_pending"].append(entity.meta_id)
        else:
            try:
                result["paused_local"] += (
                    pause(connection, entity.id, reason="panic: freio solicitado") is not None
                )
            except Exception:
                result["errors"].append(entity.id)
    return result
