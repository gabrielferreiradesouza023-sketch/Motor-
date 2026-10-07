"""Leitura determinística de intenções órfãs/incertas; Actions nunca são editadas."""

from datetime import UTC, datetime

from arb.models import Action


def pending(connection, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    rows = connection.execute(
        "SELECT a.payload,EXISTS(SELECT 1 FROM actions r WHERE r.action_attempt_id=a.id) "
        "FROM actions a WHERE a.action_result='intent' AND NOT EXISTS "
        "(SELECT 1 FROM actions r WHERE r.action_attempt_id=a.id AND r.action_result!='uncertain') "
        "ORDER BY a.id"
    )
    result = []
    for payload, has_outcome in rows:
        action = Action.model_validate_json(payload)
        result.append(
            {
                "attempt_id": action.id,
                "entity_id": action.payload_json.get("entity_id"),
                "meta_id": action.payload_json.get("meta_id"),
                "kind": action.kind,
                "age_seconds": max(0, int((now - action.ts).total_seconds())),
                "state": "uncertain" if has_outcome else "orphan",
            }
        )
    return sorted(result, key=lambda item: item["attempt_id"])


def require_clear(connection, entity_id: str) -> None:
    if any(p["entity_id"] == entity_id for p in pending(connection)):
        raise ValueError("pendência aberta: reconciliar antes de nova escrita")
