"""Somente pausa autônoma; qualquer ativação precisa de outra aprovação humana."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from arb import safety
from arb.db import Repository
from arb.launcher.execute import approved_file, require_simulation, store_approval
from arb.meta.pause import PauseWriter
from arb.models import Action, Entity


def pause(
    connection: sqlite3.Connection,
    entity_id: str,
    *,
    reason: str,
    now: datetime | None = None,
    writer: PauseWriter | None = None,
) -> Action | None:
    live = safety.live_mode()
    safety.require_external_write("pause", simulation=not live)
    if not reason.strip():
        raise ValueError("pausa precisa de motivo auditável")
    entity = Repository(connection, Entity).get(entity_id)
    if entity is None:
        raise ValueError("entidade desconhecida")
    if entity.meta_id is not None and not live:
        raise ValueError("pausa real pendente: não alterar estado observado da Meta localmente")
    if connection.in_transaction:
        raise ValueError("pausa requer conexão sem transação pendente")
    if entity.meta_id is not None:
        return _pause_remote(connection, entity, reason, now or datetime.now(UTC), writer)
    # Releitura dentro da transação impede duplicação em concorrência.
    connection.execute("BEGIN IMMEDIATE")
    try:
        entity = Repository(connection, Entity).get(entity_id)
        if entity.status == "paused":
            connection.rollback()
            return None
        action = Action(
            id=str(uuid4()),
            ts=now or datetime.now(UTC),
            actor="engine",
            kind="pause",
            payload_json={
                "entity_id": entity.id,
                "input": {"status": entity.status},
                "output": {"status": "paused"},
                "reason": reason,
            },
            live=False,
            result="simulated",
        )
        entity.status = "paused"
        Repository(connection, Entity).update(entity)
        Repository(connection, Action).add(action)
        connection.commit()
        return action
    except Exception:
        connection.rollback()
        raise


def activation_intent(entity: Entity) -> dict:
    return {
        "kind": "activate",
        "entity_id": entity.id,
        "from_status": "paused",
        "to_status": "active",
        "daily_budget_cents": entity.daily_budget_cents,
        "geo": entity.geo,
        "offer_id": entity.offer_id,
        "parent_id": entity.parent_id,
    }


def intent_hash(intent: dict) -> str:
    return hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def activate(
    connection: sqlite3.Connection,
    entity_id: str,
    approval_id: str,
    *,
    approval_dir: Path = Path("ops/approvals/approved"),
    now: datetime | None = None,
) -> Action:
    from arb.quarantine import require_released

    require_released(connection)
    require_simulation()
    if connection.in_transaction:
        raise ValueError("ativação requer conexão sem transação pendente")
    now = now or datetime.now(UTC)
    from arb.db.checkpoint import snapshot_before

    snapshot_before(connection, "activate", approval_id)
    connection.execute("BEGIN IMMEDIATE")
    try:
        entity = Repository(connection, Entity).get(entity_id)
        if entity is None or entity.meta_id is not None:
            raise ValueError("ativação somente de entidade simulada conhecida")
        intent = activation_intent(entity)
        fingerprint = intent_hash(intent)
        # Campanha/conjunto exige autorização para toda a verba dos descendentes,
        # mesmo quando a própria entidade tem orçamento ABO zero.
        all_entities = Repository(connection, Entity).list()
        family = {entity.id}
        while True:
            expanded = family | {e.id for e in all_entities if e.parent_id in family}
            if expanded == family:
                break
            family = expanded
        exposure = sum(e.daily_budget_cents for e in all_entities if e.id in family)
        if entity.kind == "ad":
            parent = Repository(connection, Entity).get(entity.parent_id)
            if parent is None:
                raise ValueError("anúncio sem conjunto")
            exposure = parent.daily_budget_cents
        approval = approved_file(
            approval_id,
            kind="activate",
            fingerprint=fingerprint,
            exposure=exposure,
            directory=approval_dir,
            now=now,
        )
        # Uma aprovação só autoriza uma transição. Não reutilizar após outra pausa.
        action_id = "activate-" + approval.id
        existing = Repository(connection, Action).get(action_id)
        if existing:
            if existing.payload_json["input"] != intent:
                raise ValueError("aprovação já consumida para outra intenção")
            connection.rollback()
            return existing
        if entity.status != "paused":
            raise ValueError("entidade não está pausada")
        store_approval(connection, approval)
        entity.status = "active"
        Repository(connection, Entity).update(entity)
        action = Action(
            id=action_id,
            ts=now,
            actor="engine",
            kind="activate",
            payload_json={"input": intent, "output": {"status": "active"}, "entity_id": entity.id},
            approval_id=approval.id,
            live=False,
            result="simulated",
        )
        Repository(connection, Action).add(action)
        connection.commit()
        return action
    except Exception:
        connection.rollback()
        raise


def automatic(connection: sqlite3.Connection, kind: str, entity_id: str, *, reason: str):
    if kind != "pause":
        raise ValueError(
            "somente pausa automática; criação/ativação/aumento exige aprovação humana"
        )
    return pause(connection, entity_id, reason=reason)


def _pause_remote(connection, entity, reason, now, writer):
    from arb.ledger import require_clear

    require_clear(connection, entity.id)
    if entity.status == "paused":
        return None
    writer = writer or PauseWriter.from_environment()
    identifier = str(uuid4())
    intent = Action(
        id=identifier,
        ts=now,
        actor="engine",
        kind="pause",
        payload_json={
            "entity_id": entity.id,
            "meta_id": entity.meta_id,
            "input": {"status": entity.status},
            "output": {"status": "PAUSED"},
            "reason": reason,
        },
        live=True,
        result="intent",
    )
    # Intenção durável ANTES de HTTP; falha/ACK incerto nunca falsifica estado local.
    with connection:
        Repository(connection, Action).add(intent)
    try:
        result = writer.pause(entity.meta_id)
        if result["status"] not in {"paused", "already_paused"}:
            raise ValueError("pausa desabilitada")
    except Exception:
        with connection:
            Repository(connection, Action).add(
                Action(
                    id=identifier + "-result",
                    ts=now,
                    actor="engine",
                    kind="pause_result",
                    payload_json={"attempt_id": identifier, "entity_id": entity.id},
                    live=True,
                    result="uncertain",
                )
            )
        raise ValueError("pausa remota não confirmada; conferir estado com leitura Meta") from None
    with connection:
        current = Repository(connection, Entity).get(entity.id)
        current.status = "paused"
        Repository(connection, Entity).update(current)
        Repository(connection, Action).add(
            Action(
                id=identifier + "-result",
                ts=now,
                actor="engine",
                kind="pause_result",
                payload_json={
                    "attempt_id": identifier,
                    "entity_id": entity.id,
                    "output": {"status": "PAUSED"},
                },
                live=True,
                result="paused",
            )
        )
    return intent
