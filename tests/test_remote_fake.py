import inspect

import pytest

from arb.remote import RemoteWriter
from arb.remote.fake import FAULTS, FakeMeta, RemoteError


def entity(records):
    return records[3].model_copy(update={"meta_id": None, "status": "paused"})


def test_determinism_reads_and_replay(records):
    first, second = FakeMeta(), FakeMeta()
    record = entity(records)
    created = first.create(record, "creation")
    assert second.create(record, "creation") == created
    assert first.create(record, "creation") == created
    assert len(first.entities) == 1 and len(first.effects) == 1
    identifier = created["meta_id"]
    first.activate(identifier, "activation")
    first.set_budget(identifier, 2400, "scale")
    first.pause(identifier, "pause")
    assert first.read(identifier).status == "paused"
    assert first.read(identifier).daily_budget_cents == 2400
    assert first.locate("creation") == first.read(identifier)
    assert first.ads() == [{"id": identifier, "status": "PAUSED"}]
    clone = first.read(identifier)
    clone.status = "active"
    assert first.read(identifier).status == "paused"
    assert isinstance(first, RemoteWriter)
    assert not hasattr(first, "delete")
    assert "import httpx" not in inspect.getsource(type(first))


@pytest.mark.parametrize("operation", ["create", "activate", "scale", "pause"])
@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_failure_effect_boundary(records, operation, fault):
    fake = FakeMeta()
    record = entity(records)
    identifier = fake.create(record, "seed")["meta_id"] if operation != "create" else None
    if operation == "pause":
        fake.activate(identifier, "seed-active")
    before = len(fake.effects)
    fake.fail_next(operation, fault)

    def call():
        if operation == "create":
            return fake.create(record, "test")
        if operation == "activate":
            return fake.activate(identifier, "test")
        if operation == "scale":
            return fake.set_budget(identifier, 2400, "test")
        return fake.pause(identifier, "test")

    if fault == "invalid_response":
        assert call() == {}
    else:
        with pytest.raises((TimeoutError, RemoteError)):
            call()
    applied = fault in {"after_timeout", "invalid_response"}
    assert len(fake.effects) == before + int(applied)
    result = call()
    assert result["status"] == ("active" if operation == "activate" else "paused")
    assert len(fake.effects) == before + 1


def test_invalid_intents_and_unknown_read(records):
    fake = FakeMeta()
    record = entity(records)
    for op, fault in [("delete", "before_timeout"), ("pause", "unknown")]:
        with pytest.raises(ValueError):
            fake.fail_next(op, fault)
    assert fake.read("missing") is None and fake.locate("missing") is None
    with pytest.raises(ValueError):
        fake.create(record.model_copy(update={"status": "active"}), "test")
    with pytest.raises(ValueError):
        fake.create(record, "")
    identifier = fake.create(record, "seed")["meta_id"]
    with pytest.raises(ValueError, match="outra intenção"):
        fake.activate(identifier, "seed")
    with pytest.raises(ValueError, match="desconhecida"):
        fake.pause("missing", "unknown")
    with pytest.raises(ValueError):
        fake.set_budget(identifier, -1, "invalid-budget")
    assert len(fake.effects) == 1


def test_call_hook_observes_before_effect(records):
    fake = FakeMeta(on_call=lambda call: observed.append((call["operation"], len(fake.entities))))
    observed = []
    fake.create(entity(records), "test")
    assert observed == [("create", 0)]
