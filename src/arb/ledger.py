"""Leitura determinística de intenções órfãs/incertas; Actions nunca são editadas."""

from datetime import UTC, datetime

from arb.db import Repository
from arb.models import Action


def pending(connection, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    actions = Repository(connection, Action).list()
    result = []
    for action in actions:
        if action.result != "intent":
            continue
        outcomes = [a for a in actions if a.payload_json.get("attempt_id") == action.id]
        if any(a.result != "uncertain" for a in outcomes):
            continue
        result.append(
            {
                "attempt_id": action.id,
                "entity_id": action.payload_json.get("entity_id"),
                "meta_id": action.payload_json.get("meta_id"),
                "kind": action.kind,
                "age_seconds": max(0, int((now - action.ts).total_seconds())),
                "state": "uncertain" if outcomes else "orphan",
            }
        )
    return sorted(result, key=lambda item: item["attempt_id"])


def require_clear(connection, entity_id: str) -> None:
    if any(p["entity_id"] == entity_id for p in pending(connection)):
        raise ValueError("pendência aberta: reconciliar antes de nova escrita")
