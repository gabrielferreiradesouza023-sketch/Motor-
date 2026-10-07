import json
from datetime import UTC, datetime

import httpx
import pytest
from test_execute import setup_launch
from typer.testing import CliRunner

import arb.accept_pause as kit
from arb.cli import app
from arb.db import Repository
from arb.launcher.execute import execute
from arb.ledger import pending
from arb.meta.pause import PauseWriter
from arb.meta.read import Reader
from arb.models import Action, Entity
from arb.reconcile import reconcile

NOW = datetime(2026, 10, 7, tzinfo=UTC)
META_ID = "123456789"


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    conn, plan, approval, directory = setup_launch(tmp_path)
    execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out")
    entity = next(e for e in plan.entities if e.kind == "ad")
    entity = entity.model_copy(update={"meta_id": META_ID, "status": "active"})
    with conn:
        Repository(conn, Entity).update(entity)
    monkeypatch.setattr(kit, "is_interactive", lambda: True)
    kit.register_test(conn, META_ID, confirm=lambda message: META_ID in message, now=NOW)
    yield conn, entity
    conn.close()


def transport(conn, fault=None, initial="ACTIVE"):
    calls = []
    state = {"status": initial, "reads": 0}

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            # Independent durable ledger must exist before even the first write.
            assert pending(conn) and not conn.in_transaction
            assert request.content == b"status=PAUSED"
            assert request.url.path.endswith("/" + META_ID)
            state["status"] = "PAUSED"
            if fault == "post_timeout":
                raise httpx.ReadTimeout("synthetic-hidden")
            return httpx.Response(200, json={"success": True})
        state["reads"] += 1
        if fault == "read_before":
            raise httpx.ReadTimeout("synthetic-hidden")
        if fault == "get_after" and state["reads"] == 2:
            raise httpx.ReadTimeout("synthetic-hidden")
        status = "ACTIVE" if fault == "not_paused" and state["reads"] == 2 else state["status"]
        return httpx.Response(200, json={"data": [{"id": META_ID, "status": status}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reader = Reader("synthetic-hidden", "123", "v99.0", client=client, attempts=1)
    writer = PauseWriter("synthetic-hidden", "v99.0", client=client)
    return client, reader, writer, calls, state


@pytest.mark.parametrize(
    "fault,initial",
    [
        (None, "ACTIVE"),
        (None, "PAUSED"),
        ("post_timeout", "ACTIVE"),
        ("get_after", "ACTIVE"),
        ("not_paused", "ACTIVE"),
    ],
)
def test_pause_matrix_durable_readback(seeded, monkeypatch, fault, initial):
    conn, entity = seeded
    monkeypatch.setenv("LIVE_MODE", "true")
    client, reader, writer, calls, _ = transport(conn, fault, initial)
    with client:
        result = kit.pause(
            conn, META_ID, reader, writer, confirm=lambda message: META_ID in message, now=NOW
        )
        assert result["status"] == ("failed" if fault else "passed")
        assert bool(pending(conn)) == bool(fault)
        assert "synthetic-hidden" not in json.dumps(result) and META_ID not in json.dumps(result)
        if fault:
            assert "reconcile" in result["next_step"]
            # No blind retry: an independent reader reconciles the observed pause.
            assert reconcile(conn, reader, now=NOW)["resolved"]
        assert Repository(conn, Entity).get(entity.id).status == "paused"
    assert calls.count("POST") == (0 if initial == "PAUSED" else 1)


@pytest.mark.parametrize(
    "violation",
    [
        "false",
        "tty",
        "writer",
        "naive",
        "flag",
        "flag_binding",
        "invalid_id",
        "unknown",
        "duplicate",
        "parent",
        "transaction",
        "pending",
        "quarantine",
        "status",
        "cancel",
        "change",
    ],
)
def test_pause_refusals_before_post(seeded, monkeypatch, violation):
    conn, entity = seeded
    monkeypatch.setenv("LIVE_MODE", "true")
    client, reader, writer, calls, state = transport(conn)
    identifier, now = META_ID, NOW

    def confirm(_):
        return True

    if violation == "false":
        monkeypatch.setenv("LIVE_MODE", "false")
    elif violation == "tty":
        monkeypatch.setattr(kit, "is_interactive", lambda: False)
    elif violation == "writer":
        writer = object()
    elif violation == "naive":
        now = datetime(2026, 10, 7)
    elif violation in {"flag", "flag_binding"}:
        with conn:
            conn.execute("DELETE FROM acceptance_test_entities")
            if violation == "flag_binding":
                conn.execute(
                    "INSERT INTO acceptance_test_entities VALUES (?,?)", (entity.id, "111")
                )
    elif violation == "invalid_id":
        identifier = "invalid"
    elif violation == "unknown":
        identifier = "111"
    elif violation in {"duplicate", "parent"}:
        other = next(e for e in Repository(conn, Entity).list() if e.kind == "adset")
        with conn:
            if violation == "parent":
                entity.meta_id = "111"
                Repository(conn, Entity).update(entity)
            other.meta_id = META_ID
            Repository(conn, Entity).update(other)
    elif violation == "transaction":
        conn.execute("BEGIN")
    elif violation == "pending":
        with conn:
            Repository(conn, Action).add(
                Action(
                    id="orphan",
                    ts=NOW,
                    actor="human",
                    kind="pause",
                    live=True,
                    result="intent",
                    payload_json={"entity_id": entity.id},
                )
            )
    elif violation == "quarantine":
        with conn:
            conn.execute(
                "INSERT INTO restore_quarantine VALUES ('q','backup',?, ?,NULL)",
                ("0" * 64, NOW.isoformat()),
            )
    elif violation == "status":
        state["status"] = "UNKNOWN"
    elif violation == "cancel":

        def confirm(_):
            return False
    elif violation == "change":

        def confirm(_):
            with conn:
                entity.status = "paused"
                Repository(conn, Entity).update(entity)
            return True

    with client, pytest.raises(ValueError):
        kit.pause(conn, identifier, reader, writer, confirm=confirm, now=now)
    assert "POST" not in calls
    conn.rollback()


@pytest.mark.parametrize("violation", ["tty", "cancel", "change"])
def test_register_refusals(seeded, monkeypatch, violation):
    conn, entity = seeded
    before = len(Repository(conn, Action).list())

    def confirm(_):
        return True

    if violation == "tty":
        monkeypatch.setattr(kit, "is_interactive", lambda: False)
    elif violation == "cancel":

        def confirm(_):
            return False
    else:

        def confirm(_):
            with conn:
                entity.status = "paused"
                Repository(conn, Entity).update(entity)
            return True

    with pytest.raises(ValueError):
        kit.register_test(conn, META_ID, confirm=confirm)
    assert len(Repository(conn, Action).list()) == before


def test_cli_refusals_no_live_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    result = CliRunner().invoke(
        app, ["accept", "pause", "--meta-id", META_ID, "--out", str(tmp_path / "proof.json")]
    )
    assert result.exit_code == 1 and not (tmp_path / "proof.json").exists()
    result = CliRunner().invoke(
        app,
        ["accept", "register-test", "--meta-id", META_ID, "--database", str(tmp_path / "local.db")],
    )
    assert result.exit_code == 1


def test_before_read_error_is_sanitized_without_intent(seeded, monkeypatch):
    conn, _ = seeded
    monkeypatch.setenv("LIVE_MODE", "true")
    client, reader, writer, calls, _ = transport(conn, "read_before")
    with client, pytest.raises(ValueError, match="nenhuma pausa") as error:
        kit.pause(conn, META_ID, reader, writer, now=NOW)
    assert "synthetic-hidden" not in str(error.value)
    assert calls == ["GET"] and pending(conn) == []
