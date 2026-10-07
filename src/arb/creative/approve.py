"""Proposta e consumo assinado do conjunto exato de ângulos/criativos."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from arb.creative.copy import lint_copy
from arb.db import Repository
from arb.launcher.approval import read_document
from arb.launcher.execute import approved_file, require_simulation, store_approval
from arb.models import Action, Angle, Approval, Creative, Offer
from arb.quarantine import require_released


def eligible(creative):
    return creative.policy_lint == "passed" and not lint_copy(
        creative.headline + " " + creative.copy_primary
    )


def propose(connection, offer_id, *, directory=Path("ops/approvals/pending")) -> Path:
    require_simulation()
    offer = Repository(connection, Offer).get(offer_id)
    if offer is None or offer.status != "approved":
        raise ValueError("oferta precisa de aprovação new_offer")
    angles = [a for a in Repository(connection, Angle).list() if a.offer_id == offer_id]
    creatives = [
        c
        for c in Repository(connection, Creative).list()
        if c.angle_id in {a.id for a in angles} and eligible(c)
    ]
    angles = [a for a in angles if a.id in {c.angle_id for c in creatives}]
    if not creatives:
        raise ValueError("nenhum criativo elegível")
    plan = {
        "kind": "creative_set",
        "angles": [a.model_dump(mode="json") for a in angles],
        "creatives": [c.model_dump(mode="json") for c in creatives],
    }
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    approval = Approval(
        id="creative-set-" + digest,
        plan_hash=digest,
        kind="creative_set",
        summary=f"Revisar {len(angles)} ângulos e {len(creatives)} criativos de {offer.name}",
        max_exposure_cents=0,
        status="pending",
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (approval.id + ".json")
    payload = (
        json.dumps(
            {"approval": approval.model_dump(mode="json"), "plan": plan},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
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
        raise ValueError("criativos exigem commit anterior")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
        raise ValueError("id de aprovação inválido")
    path = directory / (approval_id + ".json")
    if path.is_symlink():
        raise ValueError("aprovação não pode ser symlink")
    proposed, plan = read_document(path)
    if plan is None or set(plan) != {"kind", "angles", "creatives"}:
        raise ValueError("conjunto da proposta ausente")
    now = now or datetime.now(UTC)
    approval = approved_file(
        approval_id,
        kind="creative_set",
        fingerprint=proposed.plan_hash,
        exposure=0,
        directory=directory,
        now=now,
    )
    angles = [Angle.model_validate(a) for a in plan["angles"]]
    creatives = [Creative.model_validate(c) for c in plan["creatives"]]
    if (
        not angles
        or not creatives
        or len({a.id for a in angles}) != len(angles)
        or len({c.id for c in creatives}) != len(creatives)
    ):
        raise ValueError("conjunto vazio ou duplicado")
    if any(c.angle_id not in {a.id for a in angles} or not eligible(c) for c in creatives):
        raise ValueError("criativo sem ângulo ou lint válido")
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = Repository(connection, Action).get("creative-set-apply-" + approval.id)
        if existing:
            connection.rollback()
            return existing
        for model, records in ((Angle, angles), (Creative, creatives)):
            for record in records:
                if Repository(connection, model).get(record.id) != record:
                    raise ValueError("criativo/ângulo alterado depois da proposta")
        store_approval(connection, approval)
        for model, records in ((Angle, angles), (Creative, creatives)):
            for record in records:
                record.status = "approved"
                Repository(connection, model).update(record)
        action = Action(
            id="creative-set-apply-" + approval.id,
            ts=now,
            actor="engine",
            kind="creative_set_apply",
            payload_json={"input": plan},
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
