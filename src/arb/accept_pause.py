"""Aceite humano de uma pausa, com intenção durável e confirmação por leitura."""

import re
from datetime import UTC, datetime
from uuid import uuid4

import typer

from arb.accept import evidence, require_host, suffix
from arb.db import Repository
from arb.launcher.approval import is_interactive
from arb.ledger import pending
from arb.meta.pause import PauseWriter
from arb.models import Action, Entity
from arb.quarantine import require_released
from arb.reconcile import observed_statuses


def eligible(connection, meta_id, *, flagged=True):
    if connection.in_transaction:
        raise ValueError("commit anterior obrigatório")
    require_released(connection)
    if pending(connection):
        raise ValueError("reconciliar pendências antes do kit")
    if not re.fullmatch(r"[0-9]+", meta_id):
        raise ValueError("id numérico obrigatório")
    entities = [e for e in Repository(connection, Entity).list() if e.meta_id == meta_id]
    if len(entities) != 1 or entities[0].kind != "ad":
        raise ValueError("anúncio local único obrigatório; não usar campanha/conjunto")
    entity = entities[0]
    if flagged and connection.execute(
        "SELECT meta_id FROM acceptance_test_entities WHERE entity_id=?", (entity.id,)
    ).fetchone() != (meta_id,):
        raise ValueError("entidade não registrada explicitamente como teste")
    return entity


def register_test(connection, meta_id, *, confirm=None, now=None):
    if not is_interactive():
        raise ValueError("cadastro exige tty humano")
    entity = eligible(connection, meta_id, flagged=False)
    confirm = confirm or typer.confirm
    if not confirm(f"Confirmar que o anúncio {meta_id} foi criado manualmente SOMENTE para teste?"):
        raise ValueError("cadastro cancelado")
    # Revalidar depois da confirmação, antes de publicar a flag vinculada ao id remoto.
    if eligible(connection, meta_id, flagged=False) != entity:
        raise ValueError("entidade alterada durante confirmação")
    with connection:
        connection.execute(
            "INSERT INTO acceptance_test_entities VALUES (?,?) ON CONFLICT(entity_id) "
            "DO UPDATE SET meta_id=excluded.meta_id",
            (entity.id, meta_id),
        )
        Repository(connection, Action).add(
            Action(
                id="accept-register-" + uuid4().hex,
                ts=now or datetime.now(UTC),
                actor="human",
                kind="accept_register_test",
                live=False,
                result="registered",
                payload_json={"entity_id": entity.id, "meta_id": meta_id},
            )
        )
    return entity


def pause(connection, meta_id, reader, writer: PauseWriter, *, confirm=None, now=None):
    require_host()
    if not is_interactive():
        raise ValueError("pausa de aceite exige tty humano")
    if not isinstance(writer, PauseWriter):
        raise ValueError("kit admite somente PauseWriter")
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("timestamp com fuso obrigatório")
    entity = eligible(connection, meta_id)
    try:
        before = observed_statuses(reader).get(meta_id)
    except Exception:
        raise ValueError("leitura anterior falhou; nenhuma pausa enviada") from None
    if before not in {"ACTIVE", "PAUSED"}:
        raise ValueError("estado anterior ausente/desconhecido")
    confirm = confirm or typer.confirm
    if not confirm(f"Pausar SOMENTE o anúncio de teste {meta_id}, estado {before}?"):
        raise ValueError("pausa cancelada")
    if eligible(connection, meta_id) != entity:
        raise ValueError("entidade alterada durante confirmação")
    attempt = "accept-pause-" + uuid4().hex
    actions = Repository(connection, Action)
    with connection:
        actions.add(
            Action(
                id=attempt,
                ts=now,
                actor="human",
                kind="pause",
                live=True,
                result="intent",
                payload_json={"entity_id": entity.id, "meta_id": meta_id},
            )
        )
    try:
        writer.pause(meta_id, already_paused=before == "PAUSED")
        after = observed_statuses(reader).get(meta_id)
        if after != "PAUSED":
            raise ValueError("pausa não confirmada por GET")
    except Exception:
        with connection:
            actions.add(
                Action(
                    id=attempt + "-uncertain",
                    ts=now,
                    actor="human",
                    kind="pause_result",
                    live=True,
                    result="uncertain",
                    payload_json={"attempt_id": attempt, "entity_id": entity.id},
                )
            )
        return evidence(
            "f6_pause",
            [{"name": "observed_paused", "ok": False}],
            now=now,
            meta_suffix=suffix(meta_id),
            next_step="arb ops reconcile no host humano; não repetir POST",
        )
    with connection:
        entity.status = "paused"
        Repository(connection, Entity).update(entity)
        actions.add(
            Action(
                id=attempt + "-confirmed",
                ts=now,
                actor="human",
                kind="pause_result",
                live=True,
                result="reconciled_paused",
                payload_json={
                    "attempt_id": attempt,
                    "entity_id": entity.id,
                    "output": {"status": after},
                },
            )
        )
    return evidence(
        "f6_pause",
        [{"name": "observed_paused", "ok": True}],
        now=now,
        meta_suffix=suffix(meta_id),
        before=before,
        after=after,
    )
