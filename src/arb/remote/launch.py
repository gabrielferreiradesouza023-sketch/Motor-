"""Launch pausado sobre FakeMeta, com um journal por item do plano."""

import hashlib

from arb.db import Repository
from arb.db.checkpoint import snapshot_before
from arb.launcher import plan_hash
from arb.launcher.execute import store_approval
from arb.ledger import pending
from arb.models import Action, Angle, Creative, Entity, Offer
from arb.remote.journal import perform, require_fake


def execute(connection, value, approval, writer, *, now):
    require_fake(writer)
    if pending(connection):
        raise ValueError("reconciliar antes de launch")
    fingerprint = plan_hash(value)
    existing = Repository(connection, Action).get("launch-" + fingerprint)
    if existing:
        return existing
    for model, records in (
        (Offer, [value.offer]),
        (Angle, value.angles),
        (Creative, value.creatives),
    ):
        if any(Repository(connection, model).get(record.id) != record for record in records):
            raise ValueError("entradas do plano divergem do banco")
    snapshot_before(connection, "launch", fingerprint)
    with connection:
        store_approval(connection, approval)
        for entity in value.entities:
            current = Repository(connection, Entity).get(entity.id)
            if current is None:
                Repository(connection, Entity).add(entity)
    for entity in value.entities:
        key = "create-" + hashlib.sha256((fingerprint + ":" + entity.id).encode()).hexdigest()
        current = Repository(connection, Entity).get(entity.id)
        perform(
            connection,
            writer,
            current,
            "create",
            key,
            context=value.model_dump(mode="json"),
            approval=approval,
            now=now,
        )
    action = Action(
        id="launch-" + fingerprint,
        ts=now,
        actor="engine",
        kind="launch",
        payload_json={
            "plan_hash": fingerprint,
            "input": value.model_dump(mode="json"),
            "output": {"entities": len(value.entities), "status": "paused"},
        },
        approval_id=approval.id,
        live=False,
        result="fake_applied",
    )
    with connection:
        Repository(connection, Action).add(action)
    return action
