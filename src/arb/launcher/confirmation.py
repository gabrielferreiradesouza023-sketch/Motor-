"""Signed extra confirmation slice; permission never changes status or budget."""

import hashlib
import json
from datetime import datetime, timedelta

from arb.db import Repository
from arb.launcher.approval import read_document, verify
from arb.launcher.execute import store_approval
from arb.models import Action, Approval, Decision, Entity
from arb.permissions import private_open, reject_links
from arb.rules import confirmation_context, load_rules

KIND = "gate_c_confirmation"
FIELDS = {
    "kind",
    "entity_id",
    "geo",
    "offer_id",
    "confirmation_start_cents",
    "extra_cap_cents",
    "total_cap_cents",
    "expires_at",
}
REQUIRED = "C exige aprovação assinada válida: entidade/geo/oferta/baseline/teto/validade"


def digest(plan):
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def context(entity, baseline, rules):
    if rules.gate_C is None or type(baseline) is not int or baseline < 0:
        raise ValueError("C desligado ou baseline ausente/inválido")
    return {
        "kind": KIND,
        "entity_id": entity.id,
        "geo": entity.geo,
        "offer_id": entity.offer_id,
        "confirmation_start_cents": baseline,
        "extra_cap_cents": rules.gate_C.cap_cents,
        "total_cap_cents": baseline + rules.gate_C.cap_cents,
    }


def valid_context(plan, expected, now):
    if not isinstance(plan, dict) or set(plan) != FIELDS:
        return False
    for key in ("confirmation_start_cents", "extra_cap_cents", "total_cap_cents"):
        if type(plan[key]) is not int:
            return False
    if {k: v for k, v in plan.items() if k != "expires_at"} != expected:
        return False
    try:
        expires = datetime.fromisoformat(plan["expires_at"])
        return expires.utcoffset() is not None and now < expires
    except (ValueError, TypeError):
        return False


def documents(directory):
    reject_links(directory)
    for path in sorted(directory.glob("gate-c-*.json")):
        try:
            reject_links(path)
            if not path.is_file() or path.stat().st_nlink != 1:
                continue
            approval, plan = read_document(path)
            if path.name == approval.id + ".json":
                yield path, approval, plan
        except (ValueError, OSError):
            continue  # malformed untrusted artifact never authorizes exposure


def authorized(entity, baseline, rules, now, directory):
    expected = context(entity, baseline, rules)
    for _, approval, plan in documents(directory):
        if (
            approval.kind != KIND
            or approval.status != "approved"
            or not valid_context(plan, expected, now)
            or approval.max_exposure_cents < rules.gate_C.cap_cents
            or approval.decided_at is None
            or approval.decided_at > now
        ):
            continue
        try:
            verify(approval)
        except (ValueError, OSError):
            continue
        return approval
    raise ValueError(REQUIRED)


def propose(connection, entity, baseline, rules, now, directory):
    expected = context(entity, baseline, rules)
    for path, approval, plan in documents(directory):
        if approval.status == "pending" and valid_context(plan, expected, now):
            return path
    plan = expected | {"expires_at": (now + timedelta(hours=24)).isoformat()}
    fingerprint = digest(plan)
    approval = Approval(
        id="gate-c-" + fingerprint,
        kind=KIND,
        plan_hash=fingerprint,
        summary=f"Confirmação C {entity.id}/{entity.geo}: início {baseline}, "
        f"extra {rules.gate_C.cap_cents}, total {plan['total_cap_cents']} centavos; "
        f"expira {plan['expires_at']}; não ativa nem aumenta orçamento",
        max_exposure_cents=rules.gate_C.cap_cents,
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
    path = directory / (approval.id + ".json")
    if path.exists():
        raise ValueError("proposta existente divergente")
    else:
        with private_open(path, exclusive=True) as stream:
            stream.write(payload)
    with connection:
        if Repository(connection, Approval).get(approval.id) is None:
            Repository(connection, Approval).add(approval)
    return path


def admit(connection, entity, approval, now):
    """Persist only the C gate; activation requires its own approved intent."""
    with connection:
        store_approval(connection, approval)
        entity.gate = "C"
        Repository(connection, Entity).update(entity)
        action_id = "gate-c-admit-" + approval.id
        if Repository(connection, Action).get(action_id) is None:
            Repository(connection, Action).add(
                Action(
                    id=action_id,
                    ts=now,
                    actor="engine",
                    kind=KIND,
                    payload_json={
                        "entity_id": entity.id,
                        "input": {"gate": "3"},
                        "output": {
                            "gate": "C",
                            "status": entity.status,
                            "daily_budget_cents": entity.daily_budget_cents,
                        },
                    },
                    approval_id=approval.id,
                    live=False,
                    result="authorized",
                )
            )


def require_family(connection, entity_id, *, directory, now):
    rules = load_rules()
    if rules.gate_C is None:
        return
    entities = Repository(connection, Entity).list()
    family = {entity_id}
    while True:
        expanded = family | {e.id for e in entities if e.parent_id in family}
        if expanded == family:
            break
        family = expanded
    decisions = Repository(connection, Decision).list()
    for entity in entities:
        if entity.id not in family or entity.gate not in {"3", "C"}:
            continue
        baseline, _ = confirmation_context(entity, decisions)
        capped_candidate = any(
            d.entity_id == entity.id
            and d.gate == "3"
            and d.metrics_json.get("spend_gross", -1)
            >= d.metrics_json.get("cap_cents", float("inf"))
            for d in decisions
        )
        if entity.gate == "C" or (baseline is not None and capped_candidate):
            authorized(entity, baseline, rules, now, directory)
