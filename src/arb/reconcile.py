"""Reconciliação append-only por observação; jamais escreve no provedor."""

from datetime import UTC, datetime

from arb.db import Repository
from arb.ledger import pending
from arb.models import Action, Entity


def observed_statuses(reader) -> dict[str, str]:
    result = {}
    for ad in reader.ads():
        for item in (ad, ad.get("adset", {}), ad.get("adset", {}).get("campaign", {})):
            if item.get("id"):
                identifier = str(item["id"])
                status = item.get("status")
                if identifier in result and result[identifier] != status:
                    result[identifier] = "CONFLICT"
                else:
                    result[identifier] = status
    return result


def reconcile(connection, reader, *, now=None) -> dict:
    if connection.in_transaction:
        raise ValueError("reconciliação requer commit anterior")
    from arb.remote.fake import FakeMeta

    if isinstance(reader, FakeMeta):
        from arb.remote.journal import reconcile_fake

        return reconcile_fake(connection, reader, now=now)
    now = now or datetime.now(UTC)
    rows = pending(connection, now=now)
    result = {"resolved": [], "alerts": []}
    if not rows:
        return result
    try:
        statuses = observed_statuses(reader)
    except Exception:
        result["alerts"].append("leitura Meta falhou: pendências preservadas")
        return result
    for row in rows:
        status = statuses.get(row["meta_id"])
        entity = Repository(connection, Entity).get(row["entity_id"])
        if row["kind"] != "pause" or entity is None:
            result["alerts"].append("pendência não reconciliável por pausa")
            continue
        if status not in {"ACTIVE", "PAUSED"}:
            result["alerts"].append("status desconhecido/ausente: pendência preservada")
            continue
        with connection:
            # Releitura impede registro repetido se outro reconciliador já fechou a intenção.
            if not any(p["attempt_id"] == row["attempt_id"] for p in pending(connection)):
                continue
            if status == "PAUSED":
                entity.status = "paused"
                Repository(connection, Entity).update(entity)
            Repository(connection, Action).add(
                Action(
                    id=row["attempt_id"] + "-reconciled",
                    ts=now,
                    actor="engine",
                    kind="pause_result",
                    live=False,
                    payload_json={
                        "attempt_id": row["attempt_id"],
                        "entity_id": entity.id,
                        "output": {"status": status},
                    },
                    result="reconciled_paused" if status == "PAUSED" else "reconciled_not_paused",
                )
            )
        result["resolved"].append(row["attempt_id"])
    return result
