"""Contrato da porta do motor, sem hipótese de endpoint/payload Graph."""

import pytest

from arb.remote import RemoteWriter
from arb.remote.fake import FakeMeta


@pytest.fixture(params=[FakeMeta], ids=["FakeMeta"])
def writer(request):
    return request.param()


@pytest.fixture
def source(records):
    return records[3].model_copy(update={"status": "paused", "meta_id": None})


def creation_contract(writer, source):
    first = writer.create(source, "create-contract")
    observed = writer.read(first["meta_id"])
    assert observed is not None and observed.status == "paused"
    assert observed.model_dump(exclude={"meta_id"}) == source.model_dump(exclude={"meta_id"})
    assert writer.locate("create-contract") == observed
    return first["meta_id"]


def dedupe_contract(writer, source):
    first = writer.create(source, "dedupe-contract")
    second = writer.create(source, "dedupe-contract")
    assert second["meta_id"] == first["meta_id"]
    assert writer.locate("dedupe-contract") == writer.read(first["meta_id"])


def no_delete_contract(writer, source):
    assert not callable(getattr(writer, "delete", None))


def test_creation_paused_and_read_reference(writer, source):
    assert isinstance(writer, RemoteWriter)
    creation_contract(writer, source)


def test_same_key_does_not_duplicate(writer, source):
    dedupe_contract(writer, source)


@pytest.mark.parametrize("operation", ["create", "activate", "scale", "pause"])
def test_after_effect_timeout_recoverable_by_read(writer, source, operation):
    identifier = None if operation == "create" else creation_contract(writer, source)
    if operation == "pause":
        writer.activate(identifier, "prepare-active")
    # Future fixture must arm an approved recorded transport here, never a real API.
    writer.fail_next(operation, "after_timeout")

    def effect():
        if operation == "create":
            return writer.create(source, "lost-ack")
        if operation == "activate":
            return writer.activate(identifier, "lost-ack")
        if operation == "scale":
            return writer.set_budget(identifier, source.daily_budget_cents, "lost-ack")
        return writer.pause(identifier, "lost-ack")

    with pytest.raises(TimeoutError):
        effect()
    observed = writer.locate("lost-ack") if operation == "create" else writer.read(identifier)
    assert observed is not None
    assert observed.status == ("active" if operation == "activate" else "paused")
    assert observed.daily_budget_cents == source.daily_budget_cents
    repeated = effect()
    assert repeated["meta_id"] == observed.meta_id
    assert writer.read(observed.meta_id) == observed


def test_no_delete(writer, source):
    no_delete_contract(writer, source)


def test_budget_never_exceeds_authorized_request(writer, source):
    identifier = creation_contract(writer, source)
    approved_budget = source.daily_budget_cents
    for budget in [0, approved_budget // 2, approved_budget]:
        writer.set_budget(identifier, budget, f"approved-budget-{budget}")
        assert writer.read(identifier).daily_budget_cents == budget <= approved_budget


def test_pause_idempotent_preserves_identity_and_budget(writer, source):
    identifier = creation_contract(writer, source)
    writer.activate(identifier, "activate")
    before = writer.read(identifier)
    first = writer.pause(identifier, "same-pause")
    second = writer.pause(identifier, "same-pause")
    third = writer.pause(identifier, "other-pause")
    assert first == second == third
    assert writer.read(identifier) == before.model_copy(update={"status": "paused"})


class DuplicateWriter(FakeMeta):
    def create(self, source, key):
        result = super().create(source, key + str(len(self.entities)))
        self.creations[key] = result["meta_id"]
        return result


class ActiveWriter(FakeMeta):
    def create(self, source, key):
        result = super().create(source, key)
        self.activate(result["meta_id"], "violation")
        return self.read(result["meta_id"]).model_dump(mode="json")


class DeletingWriter(FakeMeta):
    def delete(self, identifier):
        self.entities.pop(identifier)


@pytest.mark.parametrize(
    "broken,probe",
    [
        (DuplicateWriter, dedupe_contract),
        (ActiveWriter, creation_contract),
        (DeletingWriter, no_delete_contract),
    ],
)
def test_planted_writers_fail_contract(source, broken, probe):
    with pytest.raises(AssertionError):
        probe(broken(), source)
