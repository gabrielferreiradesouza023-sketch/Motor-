from datetime import UTC, datetime

import httpx
import pytest
from test_execute import setup_launch

from arb.db import Repository
from arb.launcher.execute import execute
from arb.ledger import pending
from arb.meta.read import Reader
from arb.models import Action, Entity
from arb.reconcile import observed_statuses, reconcile

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def seed_pending(tmp_path, kind="pause"):
    conn, plan, approval, directory = setup_launch(tmp_path)
    execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
    entity = plan.entities[1].model_copy(update={"meta_id": "123", "status": "active"})
    with conn:
        Repository(conn, Entity).update(entity)
        Repository(conn, Action).add(
            Action(
                id="intent",
                ts=NOW,
                actor="engine",
                kind=kind,
                payload_json={"entity_id": entity.id, "meta_id": "123"},
                live=True,
                result="intent",
            )
        )
    return conn, entity


@pytest.mark.parametrize("status", ["PAUSED", "ACTIVE", "UNKNOWN", None])
@pytest.mark.parametrize("already_paused", [False, True])
def test_read_matrix(tmp_path, status, already_paused):
    conn, entity = seed_pending(tmp_path)
    if already_paused:
        with conn:
            entity.status = "paused"
            Repository(conn, Entity).update(entity)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(
            200, json={"data": [{"id": "123", "status": status}] if status else []}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reader = Reader("synthetic", "123", "v99.0", client=client)
        result = reconcile(conn, reader, now=NOW)
        before = Repository(conn, Action).list()
        repeated = reconcile(conn, reader, now=NOW)
    resolved = status in {"ACTIVE", "PAUSED"}
    assert bool(result["resolved"]) == resolved
    assert bool(pending(conn)) != resolved
    assert Repository(conn, Action).list() == before
    assert set(calls) == {"GET"}
    assert (Repository(conn, Entity).get(entity.id).status == "paused") == (
        already_paused or status == "PAUSED"
    )
    if resolved:
        assert repeated == {"resolved": [], "alerts": []}
        assert Repository(conn, Action).get("intent-reconciled").result in {
            "reconciled_paused",
            "reconciled_not_paused",
        }
    conn.close()


@pytest.mark.parametrize("code,body", [(400, {"error": {"code": 190}}), (503, {})])
def test_failed_read_keeps_intent(tmp_path, code, body):
    conn, _ = seed_pending(tmp_path)
    before = Repository(conn, Action).list()
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(code, json=body))
    ) as client:
        result = reconcile(conn, Reader("synthetic", "123", "v99.0", client=client, attempts=1))
    assert result["alerts"] and Repository(conn, Action).list() == before
    assert pending(conn)
    conn.close()


def test_non_pause_and_missing_entity(tmp_path):
    conn, entity = seed_pending(tmp_path, kind="launch")

    class Source:
        def ads(self):
            return [{"id": "123", "status": "PAUSED"}]

    assert reconcile(conn, Source())["alerts"]
    with conn:
        Repository(conn, Action).add(
            Action(
                id="missing",
                ts=NOW,
                actor="engine",
                kind="pause",
                payload_json={"entity_id": "missing", "meta_id": "123"},
                live=True,
                result="intent",
            )
        )
    assert len(reconcile(conn, Source())["alerts"]) == 2
    conn.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        reconcile(conn, Source())
    conn.rollback()
    conn.close()


def test_hierarchy_and_conflict():
    class Source:
        def ads(self):
            return [
                {
                    "id": "ad",
                    "status": "ACTIVE",
                    "adset": {
                        "id": "set",
                        "status": "PAUSED",
                        "campaign": {"id": "camp", "status": "ACTIVE"},
                    },
                },
                {"id": "ad", "status": "PAUSED"},
                {},
            ]

    assert observed_statuses(Source()) == {"ad": "CONFLICT", "set": "PAUSED", "camp": "ACTIVE"}


def test_concurrently_resolved_no_second_record(tmp_path, monkeypatch):
    import arb.reconcile as module

    conn, _ = seed_pending(tmp_path)
    calls = []

    def changing(*args, **kwargs):
        calls.append(1)
        return pending(conn) if len(calls) == 1 else []

    monkeypatch.setattr(module, "pending", changing)

    class Source:
        def ads(self):
            return [{"id": "123", "status": "PAUSED"}]

    assert reconcile(conn, Source()) == {"resolved": [], "alerts": []}
    assert len(Repository(conn, Action).list()) == 2
    conn.close()
