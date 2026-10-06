"""Falhas de autorização e transação: provar ausência de efeitos parciais."""

from datetime import UTC, datetime, timedelta
from importlib import import_module

import httpx
import pytest
from test_approval_signature import pending
from test_execute import setup_launch
from test_plan import launch_fixture

from arb import safety
from arb.db import Repository
from arb.launcher import plan, plan_hash
from arb.launcher.actions import activate, activation_intent, automatic, intent_hash, pause
from arb.launcher.approval import sign, sign_file
from arb.launcher.execute import approved_file, execute, store_approval
from arb.meta.pause import PauseWriter
from arb.models import Action, Approval, Entity
from arb.rules import evaluate, load_rules


@pytest.fixture
def launch(tmp_path):
    conn, value, item, directory = setup_launch(tmp_path)
    try:
        yield conn, value, item, directory
    finally:
        conn.close()


def populate(launch, tmp_path):
    conn, value, item, directory = launch
    execute(conn, value, item.id, approval_dir=directory, output=tmp_path / "out")
    return conn, value, directory


@pytest.mark.parametrize(
    "change", ["naive", "future", "wrong_entity", "gate_zero", "commission_zero"]
)
def test_rule_inputs_fail_closed(records, change):
    entity, snapshot = records[3:5]
    now, commission = snapshot.ts, 5000
    if change == "naive":
        now = datetime(2026, 10, 5)
    if change == "future":
        now -= timedelta(seconds=1)
    if change == "wrong_entity":
        snapshot = snapshot.model_copy(update={"entity_id": "other"})
    if change == "gate_zero":
        entity = entity.model_copy(update={"gate": "0"})
    if change == "commission_zero":
        entity = entity.model_copy(update={"gate": "3"})
        commission = 0
    with pytest.raises(ValueError):
        evaluate(entity, snapshot, [], commission, load_rules(), now)


@pytest.mark.parametrize("change", ["angles", "destination"])
def test_plan_invalid_structure_and_destination(change):
    offer, angles, creatives = launch_fixture()
    destination = "https://bridge.example.test"
    if change == "angles":
        angles = []
    else:
        destination = "http://bridge.example.test"
    with pytest.raises(ValueError):
        plan(
            offer, angles, creatives, geo="CO", daily_budget_cents=6000, destination_url=destination
        )


@pytest.mark.parametrize("change", ["bad_id", "missing", "symlink", "body_id", "future"])
def test_approval_file_must_be_regular_current_and_bound(launch, change):
    conn, value, item, directory = launch
    identifier = item.id
    path = directory / "human.json"
    if change == "bad_id":
        identifier = "../human"
    if change == "missing":
        identifier = "absent"
    if change == "symlink":
        target = directory / "target.json"
        path.rename(target)
        path.symlink_to(target)
    if change == "body_id":
        item.id = "different"
        path.write_text(sign(item).model_dump_json())
    if change == "future":
        item.decided_at = datetime.now(UTC) + timedelta(days=1)
        path.write_text(sign(item).model_dump_json())
    with pytest.raises(ValueError):
        approved_file(
            identifier,
            kind="launch",
            fingerprint=plan_hash(value),
            exposure=6000,
            directory=directory,
            now=datetime.now(UTC),
        )
    assert Repository(conn, Action).list() == []


def test_store_pending_to_signed_identical_and_divergent(launch):
    conn, _, item, _ = launch
    proposal = item.model_copy(update={"status": "pending", "decided_at": None, "signature": None})
    with conn:
        Repository(conn, Approval).add(proposal)
        store_approval(conn, item)
    assert Repository(conn, Approval).get(item.id) == item
    with conn:
        store_approval(conn, item)
    with pytest.raises(ValueError, match="divergente"):
        store_approval(conn, sign(item.model_copy(update={"summary": "mudou"})))
    assert Repository(conn, Approval).get(item.id) == item


@pytest.mark.parametrize("change", ["decided_pending", "changed_pending"])
def test_store_cannot_smuggle_changes_with_pending(launch, change):
    conn, _, item, _ = launch
    proposal = item.model_copy(
        update={
            "status": "pending",
            "signature": None,
            "decided_at": item.decided_at if change == "decided_pending" else None,
            "max_exposure_cents": 100 if change == "changed_pending" else 6000,
        }
    )
    with conn:
        Repository(conn, Approval).add(proposal)
    with pytest.raises(ValueError, match="divergente"):
        store_approval(conn, item)


@pytest.mark.parametrize("change", ["naive", "transaction"])
def test_execute_refuses_unowned_transaction_or_clock(launch, tmp_path, change):
    conn, value, item, directory = launch
    if change == "transaction":
        conn.execute("BEGIN")
    with pytest.raises(ValueError):
        execute(
            conn,
            value,
            item.id,
            approval_dir=directory,
            output=tmp_path / "out",
            now=datetime(2026, 10, 5) if change == "naive" else None,
        )
    conn.rollback()
    assert Repository(conn, Entity).list() == []


@pytest.mark.parametrize(
    "change", ["bad_parent", "id", "approved", "signature", "date", "directory_link"]
)
def test_sign_file_rejects_unreviewable_proposals(tmp_path, monkeypatch, change):
    source = pending(tmp_path)
    module = import_module("arb.launcher.approval")
    monkeypatch.setattr(module, "is_interactive", lambda: True)
    item = Approval.model_validate_json(source.read_text())
    if change == "bad_parent":
        directory = tmp_path / "other"
        source.parent.rename(directory)
        source = directory / source.name
    elif change == "id":
        item.id = "other"
    elif change == "approved":
        item.status = "approved"
    elif change == "signature":
        item = sign(item)
    elif change == "date":
        item.decided_at = datetime(2026, 1, 1, tzinfo=UTC)
    elif change == "directory_link":
        target = tmp_path / "other"
        target.mkdir()
        (tmp_path / "approved").symlink_to(target, target_is_directory=True)
    source.write_text(item.model_dump_json())
    with pytest.raises(ValueError):
        sign_file(source, lambda _: True)
    assert source.exists()


@pytest.mark.parametrize("change", ["reason", "unknown", "transaction"])
def test_pause_preconditions_have_no_partial_effect(launch, tmp_path, change):
    conn, value, _ = populate(launch, tmp_path)
    if change == "transaction":
        conn.execute("BEGIN")
    with pytest.raises(ValueError):
        pause(
            conn,
            "unknown" if change == "unknown" else value.entities[0].id,
            reason=" " if change == "reason" else "freio",
        )
    conn.rollback()
    assert len(Repository(conn, Action).list()) == 1


def test_local_pause_rollback_and_automatic_success(launch, tmp_path, monkeypatch):
    conn, value, _ = populate(launch, tmp_path)
    entity = value.entities[0].model_copy(update={"status": "active"})
    with conn:
        Repository(conn, Entity).update(entity)
    original = Repository.update

    def failed(self, record):
        original(self, record)
        raise RuntimeError("falha após update")

    monkeypatch.setattr(Repository, "update", failed)
    with pytest.raises(RuntimeError):
        pause(conn, entity.id, reason="freio")
    assert not conn.in_transaction
    assert Repository(conn, Entity).get(entity.id).status == "active"
    assert len(Repository(conn, Action).list()) == 1
    monkeypatch.setattr(Repository, "update", original)
    assert automatic(conn, "pause", entity.id, reason="freio").result == "simulated"


def activation_approval(entity, directory, exposure=2000):
    item = sign(
        Approval(
            id="activation",
            kind="activate",
            plan_hash=intent_hash(activation_intent(entity)),
            summary="Fixture",
            max_exposure_cents=exposure,
            status="approved",
            decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    (directory / "activation.json").write_text(item.model_dump_json())
    return item


@pytest.mark.parametrize("index", [1, 2])
def test_activate_adset_and_ad_require_parent_budget(launch, tmp_path, index):
    conn, value, directory = populate(launch, tmp_path)
    entity = value.entities[index]
    item = activation_approval(entity, directory)
    action = activate(conn, entity.id, item.id, approval_dir=directory)
    assert action.approval_id == item.id
    assert Repository(conn, Entity).get(entity.id).status == "active"


@pytest.mark.parametrize(
    "change", ["transaction", "unknown", "remote", "active", "orphan", "consumed"]
)
def test_activation_refusal_rolls_back(launch, tmp_path, change):
    conn, value, directory = populate(launch, tmp_path)
    entity = value.entities[2]
    if change == "remote":
        entity = entity.model_copy(update={"meta_id": "123"})
    if change == "active":
        entity = entity.model_copy(update={"status": "active"})
    if change == "orphan":
        entity = entity.model_copy(update={"parent_id": None})
    with conn:
        Repository(conn, Entity).update(entity)
    item = activation_approval(entity, directory)
    if change == "consumed":
        with conn:
            store_approval(conn, item)
            Repository(conn, Action).add(
                Action(
                    id="activate-activation",
                    ts=datetime.now(UTC),
                    actor="engine",
                    kind="activate",
                    payload_json={"input": {"different": True}},
                    approval_id=item.id,
                    live=False,
                    result="simulated",
                )
            )
    before = Repository(conn, Action).list()
    if change == "transaction":
        conn.execute("BEGIN")
    with pytest.raises(ValueError):
        activate(
            conn, "absent" if change == "unknown" else entity.id, item.id, approval_dir=directory
        )
    conn.rollback()
    assert Repository(conn, Action).list() == before
    assert Repository(conn, Entity).get(entity.id) == entity


def test_pause_factory_only_creates_injected_mock_client(monkeypatch):
    monkeypatch.setattr(safety, "live_mode", lambda: True)
    monkeypatch.setenv("META_ACCESS_TOKEN", "synthetic-owned-client-token")
    monkeypatch.setenv("META_API_VERSION", "v99.0")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"success": True})),
        trust_env=False,
    )
    monkeypatch.setattr(httpx, "Client", lambda **_: client)
    writer = PauseWriter.from_environment()
    assert writer.pause("123") == {"status": "paused"}
    assert client.is_closed  # owned client sempre fechado após escrita.


@pytest.mark.parametrize("token,version", [("", "v99.0"), ("synthetic", "bad")])
def test_pause_writer_rejects_missing_configuration(token, version):
    with pytest.raises(ValueError):
        PauseWriter(token, version)


def test_disabled_remote_attempt_remains_uncertain(launch, tmp_path, monkeypatch):
    conn, value, _ = populate(launch, tmp_path)
    entity = value.entities[0].model_copy(update={"meta_id": "123", "status": "active"})
    with conn:
        Repository(conn, Entity).update(entity)
    monkeypatch.setattr(safety, "live_mode", lambda: True)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("HTTP proibido")), trust_env=False
    ) as client:
        writer = PauseWriter("synthetic", "v99.0", client)
        monkeypatch.setattr(writer, "pause", lambda _: {"status": "disabled"})
        with pytest.raises(ValueError, match="não confirmada"):
            pause(conn, entity.id, reason="freio", writer=writer)
    assert Repository(conn, Entity).get(entity.id).status == "active"
    assert any(a.result == "uncertain" for a in Repository(conn, Action).list())
