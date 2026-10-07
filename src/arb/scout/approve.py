"""Consome apenas as ofertas exatas do envelope aprovado e assinado."""

import re
from datetime import UTC, datetime
from pathlib import Path

from arb.db import Repository
from arb.launcher.approval import read_document
from arb.launcher.execute import approved_file, require_simulation, store_approval
from arb.models import Action, Offer
from arb.quarantine import require_released


def apply(connection, approval_id, *, directory=Path("ops/approvals/approved"), now=None):
    require_simulation()
    require_released(connection)
    if connection.in_transaction:
        raise ValueError("ofertas exigem commit anterior")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", approval_id):
        raise ValueError("id de aprovação inválido")
    path = directory / (approval_id + ".json")
    if path.is_symlink():
        raise ValueError("aprovação não pode ser symlink")
    proposed, plan = read_document(path)
    if plan is None or set(plan) != {"kind", "offers"} or not plan["offers"]:
        raise ValueError("ofertas da proposta ausentes")
    now = now or datetime.now(UTC)
    approval = approved_file(
        approval_id,
        kind="new_offer",
        fingerprint=proposed.plan_hash,
        exposure=0,
        directory=directory,
        now=now,
    )
    records = [Offer.model_validate(o) for o in plan["offers"]]
    if len({o.id for o in records}) != len(records):
        raise ValueError("ofertas duplicadas na proposta")
    connection.execute("BEGIN IMMEDIATE")
    try:
        existing = Repository(connection, Action).get("new-offer-apply-" + approval.id)
        if existing:
            connection.rollback()
            return existing
        for offer in records:
            if Repository(connection, Offer).get(offer.id) != offer:
                raise ValueError("oferta alterada depois da proposta")
        store_approval(connection, approval)
        for offer in records:
            offer.status = "approved"
            Repository(connection, Offer).update(offer)
        action = Action(
            id="new-offer-apply-" + approval.id,
            ts=now,
            actor="engine",
            kind="new_offer_apply",
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
