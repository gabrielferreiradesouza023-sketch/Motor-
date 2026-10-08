"""Journal sintético: só FakeMeta, jamais um executor Graph."""

from datetime import UTC, datetime
from uuid import uuid4

from arb.db import Repository
from arb.launcher import plan_hash
from arb.launcher.actions import activation_intent, intent_hash
from arb.launcher.approval import verify
from arb.launcher.execute import require_simulation, store_approval
from arb.launcher.scale import digest
from arb.ledger import pending
from arb.models import Action, Approval, Decision, Entity, LaunchPlan
from arb.remote.fake import FakeMeta
from arb.rules import confirmation_context, load_rules, scale_allowed


def require_fake(writer):
    require_simulation()
    if not isinstance(writer, FakeMeta):
        raise ValueError("porta de exposição deste batch aceita somente FakeMeta")


def exposure(connection, entity):
    entities = Repository(connection, Entity).list()
    family = {entity.id}
    while True:
        grown = family | {e.id for e in entities if e.parent_id in family}
        if grown == family:
            break
        family = grown
    if entity.kind == "ad":
        parent = Repository(connection, Entity).get(entity.parent_id)
        if parent is None:
            raise ValueError("anúncio sem conjunto")
        return parent.daily_budget_cents
    return sum(e.daily_budget_cents for e in entities if e.id in family)


def authorize(connection, operation, source, context, approval, now):
    if operation == "pause":
        return source.model_copy(update={"status": "paused"})
    if approval is None:
        raise ValueError("efeito exige aprovação assinada")
    verify(approval)
    if operation == "create":
        plan = LaunchPlan.model_validate(context)
        fingerprint, kind, amount = plan_hash(plan), "launch", plan.daily_budget_cents
        if source not in plan.entities:
            raise ValueError("entidade fora do plano aprovado")
        desired = source
    elif operation == "activate":
        fingerprint, kind, amount = intent_hash(context), "activate", exposure(connection, source)
        if context != activation_intent(source):
            raise ValueError("intenção de ativação divergente")
        desired = source.model_copy(update={"status": "active"})
    elif operation == "scale":
        fingerprint, kind, amount = digest(context), "scale", context["to_budget_cents"]
        if context["entity"] != source.model_dump(mode="json") or not scale_allowed(
            load_rules(),
            source.daily_budget_cents,
            amount,
            datetime.fromisoformat(context["last_increase"]),
            now,
            approved=True,
            confirmed=confirmation_context(source, Repository(connection, Decision).list())[1],
        ):
            raise ValueError("intenção/limites de escala divergentes")
        desired = Entity.model_validate(source.model_dump() | {"daily_budget_cents": amount})
    else:
        raise ValueError("operação remota desconhecida")
    if (
        approval.kind != kind
        or approval.plan_hash != fingerprint
        or approval.max_exposure_cents < amount
        or approval.status != "approved"
        or approval.decided_at is None
        or approval.decided_at > now
    ):
        raise ValueError("aprovação não autoriza esta intenção")
    return desired


def matches(observed, desired):
    return (
        observed is not None
        and observed.meta_id is not None
        and observed.model_dump(exclude={"meta_id"}) == desired.model_dump(exclude={"meta_id"})
    )


def finish(connection, attempt, observed, *, now, reconciled=False):
    payload = attempt.payload_json
    source = Entity.model_validate(payload["source"])
    approval = (
        Repository(connection, Approval).get(attempt.approval_id) if attempt.approval_id else None
    )
    desired = authorize(
        connection, payload["operation"], source, payload["context"], approval, attempt.ts
    )
    if not matches(observed, desired) or (
        source.meta_id is not None and source.meta_id != observed.meta_id
    ):
        raise ValueError("resposta não comprova estado desejado")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if Repository(connection, Entity).get(source.id) != source:
            raise ValueError("estado local mudou durante efeito: reconciliar")
        Repository(connection, Entity).update(observed)
        final = Action(
            id=payload["key"],
            ts=now,
            actor="engine",
            kind=payload["operation"],
            payload_json={
                "input": payload["context"],
                "entity_id": source.id,
                "output": observed.model_dump(mode="json"),
                "call_key": payload["key"],
            },
            approval_id=attempt.approval_id,
            live=False,
            result="fake_applied",
        )
        Repository(connection, Action).add(final)
        Repository(connection, Action).add(
            Action(
                id=attempt.id + "-resolved",
                ts=now,
                actor="engine",
                kind=attempt.kind + "_result",
                payload_json={"attempt_id": attempt.id},
                live=False,
                result="reconciled_applied" if reconciled else "applied",
            )
        )
        connection.commit()
        return final
    except BaseException:
        connection.rollback()
        raise


def perform(connection, writer, source, operation, key, *, context, approval=None, now):
    from arb.smoke import require_automatic

    require_automatic(connection, source.id)
    require_fake(writer)
    if connection.in_transaction:
        raise ValueError("efeito exige commit anterior")
    if pending(connection):
        raise ValueError("reconciliar antes de nova tentativa")
    existing = Repository(connection, Action).get(key)
    if existing:
        return existing
    desired = authorize(connection, operation, source, context, approval, now)
    if operation != "create" and writer.read(source.meta_id) != source:
        raise ValueError("estado remoto diverge da entidade autorizada")
    attempt = Action(
        id="attempt-" + str(uuid4()),
        ts=now,
        actor="engine",
        kind=operation,
        payload_json={
            "entity_id": source.id,
            "meta_id": source.meta_id,
            "source": source.model_dump(mode="json"),
            "operation": operation,
            "key": key,
            "context": context,
            "desired": desired.model_dump(mode="json"),
        },
        approval_id=approval.id if approval else None,
        live=False,
        result="intent",
    )
    connection.execute("BEGIN IMMEDIATE")
    try:
        if pending(connection) or Repository(connection, Entity).get(source.id) != source:
            raise ValueError("estado alterado antes do efeito")
        if approval:
            store_approval(connection, approval)
        Repository(connection, Action).add(attempt)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    try:
        if operation == "create":
            raw = writer.create(source, key)
        elif operation == "activate":
            raw = writer.activate(source.meta_id, key)
        elif operation == "scale":
            raw = writer.set_budget(source.meta_id, desired.daily_budget_cents, key)
        else:
            raw = writer.pause(source.meta_id, key)
        return finish(connection, attempt, Entity.model_validate(raw), now=now)
    except Exception:
        with connection:
            Repository(connection, Action).add(
                Action(
                    id=attempt.id + "-uncertain",
                    ts=now,
                    actor="engine",
                    kind=operation + "_result",
                    payload_json={"attempt_id": attempt.id},
                    live=False,
                    result="uncertain",
                )
            )
        raise ValueError("efeito não confirmado: reconciliar antes de repetir") from None


def reconcile_fake(connection, writer, *, now=None):
    require_fake(writer)
    if connection.in_transaction:
        raise ValueError("reconciliação exige commit anterior")
    now = now or datetime.now(UTC)
    result = {"resolved": [], "alerts": []}
    for row in pending(connection, now=now):
        attempt = Repository(connection, Action).get(row["attempt_id"])
        payload = attempt.payload_json
        try:
            source = Entity.model_validate(payload["source"])
            observed = (
                writer.locate(payload["key"])
                if payload["operation"] == "create"
                else writer.read(source.meta_id)
            )
            desired = Entity.model_validate(payload["desired"])
            if matches(observed, desired):
                finish(connection, attempt, observed, now=now, reconciled=True)
            elif (payload["operation"] == "create" and observed is None) or observed == source:
                with connection:
                    Repository(connection, Action).add(
                        Action(
                            id=attempt.id + "-not-applied",
                            ts=now,
                            actor="engine",
                            kind=attempt.kind + "_result",
                            payload_json={"attempt_id": attempt.id},
                            live=False,
                            result="reconciled_not_applied",
                        )
                    )
            else:
                raise ValueError("observação desconhecida")
        except Exception:
            result["alerts"].append("observação/autoridade insuficiente: pendência preservada")
            continue
        result["resolved"].append(attempt.id)
    return result
