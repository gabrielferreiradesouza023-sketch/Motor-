"""Escala local assinada; limites são revalidados no consumo da aprovação."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from arb.db import Repository
from arb.db.checkpoint import snapshot_before
from arb.launcher.approval import read_document
from arb.launcher.execute import approved_file, require_simulation, store_approval
from arb.ledger import pending
from arb.models import Action, Approval, Entity
from arb.quarantine import require_released
from arb.rules import load_rules, scale_allowed


def last_increase(connection, entity_id):
    times = [datetime(1970, 1, 1, tzinfo=UTC)]
    for action in Repository(connection, Action).list():
        if (
            action.kind == "scale"
            and action.payload_json.get("entity_id") == entity_id
            and action.result != "intent"
        ):
            times.append(action.ts)
        if action.kind == "launch" and any(
            e["id"] == entity_id for e in action.payload_json.get("input", {}).get("entities", [])
        ):
            times.append(action.ts)
    return max(times)


def intent(connection, entity, proposed_cents):
    return {
        "kind": "scale",
        "entity_id": entity.id,
        "entity": entity.model_dump(mode="json"),
        "from_budget_cents": entity.daily_budget_cents,
        "to_budget_cents": proposed_cents,
        "last_increase": last_increase(connection, entity.id).isoformat(),
    }


def digest(plan):
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def check(connection, entity, proposed_cents, now):
    require_released(connection)
    if pending(connection):
        raise ValueError("pendência aberta: reconciliar antes de escala")
    rules = load_rules()
    if entity is None or entity.kind != "adset" or type(proposed_cents) is not int:
        raise ValueError("escala exige conjunto e orçamento inteiro")
    if not scale_allowed(
        rules,
        entity.daily_budget_cents,
        proposed_cents,
        last_increase(connection, entity.id),
        now,
        approved=True,
    ):
        raise ValueError("escala excede +20% ou intervalo mínimo de 24 h")


def propose(
    connection, entity_id, proposed_cents, *, directory=Path("ops/approvals/pending"), now=None
):
    require_simulation()
    if connection.in_transaction:
        raise ValueError("escala exige commit anterior")
    now = now or datetime.now(UTC)
    entity = Repository(connection, Entity).get(entity_id)
    check(connection, entity, proposed_cents, now)
    plan = intent(connection, entity, proposed_cents)
    fingerprint = digest(plan)
    approval = Approval(
        id="scale-" + fingerprint,
        kind="scale",
        plan_hash=fingerprint,
        summary=f"Escalar {entity.id}: {entity.daily_budget_cents} → {proposed_cents} centavos/dia",
        max_exposure_cents=proposed_cents,
        status="pending",
    )
    payload = (
        json.dumps(
            {"approval": approval.model_dump(mode="json"), "plan": plan},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (approval.id + ".json")
    if path.exists() and path.read_text() != payload:
        raise ValueError("proposta existente divergente")
    with connection:
        if Repository(connection, Approval).get(approval.id) is None:
            Repository(connection, Approval).add(approval)
    if not path.exists():
        with path.open("x") as file:
            file.write(payload)
    return path


def apply(connection, approval_id, *, directory=Path("ops/approvals/approved"), now=None):
    require_simulation()
    require_released(connection)
    if connection.in_transaction:
        raise ValueError("escala exige commit anterior")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
        raise ValueError("id de aprovação inválido")
    path = directory / (approval_id + ".json")
    if path.is_symlink():
        raise ValueError("aprovação não pode ser symlink")
    proposed, plan = read_document(path)
    if plan is None or set(plan) != {
        "kind",
        "entity_id",
        "entity",
        "from_budget_cents",
        "to_budget_cents",
        "last_increase",
    }:
        raise ValueError("intenção de escala ausente")
    now = now or datetime.now(UTC)
    approval = approved_file(
        approval_id,
        kind="scale",
        fingerprint=proposed.plan_hash,
        exposure=plan["to_budget_cents"],
        directory=directory,
        now=now,
    )
    if pending(connection):
        raise ValueError("pendência aberta: reconciliar antes de escala")
    existing = Repository(connection, Action).get("scale-apply-" + approval.id)
    if existing:
        return existing
    entity = Repository(connection, Entity).get(plan["entity_id"])
    check(connection, entity, plan["to_budget_cents"], now)
    if intent(connection, entity, plan["to_budget_cents"]) != plan:
        raise ValueError("entidade alterada depois da proposta de escala")
    snapshot_before(connection, "scale", approval.id)
    connection.execute("BEGIN IMMEDIATE")
    try:
        entity = Repository(connection, Entity).get(plan["entity_id"])
        check(connection, entity, plan["to_budget_cents"], now)
        if intent(connection, entity, plan["to_budget_cents"]) != plan:
            raise ValueError("entidade alterada durante escala")
        store_approval(connection, approval)
        entity.daily_budget_cents = plan["to_budget_cents"]
        Repository(connection, Entity).update(entity)
        action = Action(
            id="scale-apply-" + approval.id,
            ts=now,
            actor="engine",
            kind="scale",
            payload_json={
                "input": plan,
                "entity_id": entity.id,
                "output": {"daily_budget_cents": entity.daily_budget_cents},
            },
            approval_id=approval.id,
            live=False,
            result="simulated",
        )
        Repository(connection, Action).add(action)
        connection.commit()
        return action
    except BaseException:
        connection.rollback()
        raise
