"""Freio local honesto: nenhuma entidade remota é anunciada como pausada."""

import sqlite3

from arb import safety
from arb.db import Repository
from arb.launcher.actions import pause
from arb.meta.pause import PauseWriter
from arb.models import Entity


def panic(connection: sqlite3.Connection, *, writer: PauseWriter | None = None) -> dict:
    live = safety.live_mode()
    result = {
        "mode": "live" if live else "simulation",
        "paused_remote": 0,
        "paused_local": 0,
        "already_paused": 0,
        "remote_pause_pending": [],
        "errors": [],
    }
    for entity in Repository(connection, Entity).list():
        if entity.status == "paused":
            result["already_paused"] += 1
        elif entity.meta_id is not None and not live:
            result["remote_pause_pending"].append(entity.meta_id)
        else:
            try:
                key = "paused_remote" if entity.meta_id else "paused_local"
                result[key] += (
                    pause(connection, entity.id, reason="panic: freio solicitado", writer=writer)
                    is not None
                )
            except Exception:
                result["errors"].append(entity.id)
    return result
