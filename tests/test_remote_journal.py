import pytest
from test_execute import setup_launch
from test_scale import BASE, NOW, approved_scale

from arb.db import Repository
from arb.launcher.actions import activate, activation_intent, intent_hash, pause
from arb.launcher.approval import sign
from arb.launcher.execute import execute
from arb.launcher.scale import apply
from arb.ledger import pending
from arb.models import Action, Approval, Entity
from arb.reconcile import reconcile
from arb.remote.fake import FAULTS, FakeMeta


def activation(conn, entity, directory):
    approval = sign(
        Approval(
            id="activation",
            kind="activate",
            plan_hash=intent_hash(activation_intent(entity)),
            summary="Autorização sintética",
            max_exposure_cents=6000,
            status="approved",
            decided_at=BASE,
        )
    )
    (directory / "activation.json").write_text(approval.model_dump_json())
    return lambda: activate(
        conn, entity.id, approval.id, approval_dir=directory, writer=activation.writer, now=BASE
    )


@pytest.mark.parametrize("operation", ["create", "activate", "scale", "pause"])
@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_uncertain_effect_requires_read_and_never_duplicates(
    tmp_path, monkeypatch, operation, fault
):
    import arb.launcher.approval as module

    monkeypatch.setattr(module, "is_interactive", lambda: True)
    conn, plan, approval, directory = setup_launch(tmp_path)

    def before_call(call):
        intents = [
            a
            for a in Repository(conn, Action).list()
            if a.result == "intent" and a.payload_json.get("key") == call["key"]
        ]
        assert intents, "efeito sem intenção durável"
        assert pending(conn)
        if call["operation"] != "pause":
            assert Repository(conn, Approval).get(intents[-1].approval_id).signature

    writer = FakeMeta(on_call=before_call)
    activation.writer = writer

    def launch():
        return execute(
            conn,
            plan,
            approval.id,
            approval_dir=directory,
            output=tmp_path / "out",
            writer=writer,
            now=BASE,
        )

    if operation != "create":
        launch()
    entity = (
        next(e for e in Repository(conn, Entity).list() if e.kind == "adset")
        if operation != "create"
        else None
    )
    if operation == "create":
        invoke = launch
    elif operation == "activate":
        invoke = activation(conn, entity, directory)
    elif operation == "scale":
        scale_approval, path = approved_scale(conn, entity, tmp_path)

        def invoke():
            return apply(conn, scale_approval.id, directory=path.parent, now=NOW, writer=writer)
    else:
        activation(conn, entity, directory)()

        def invoke():
            return pause(conn, entity.id, reason="limite", writer=writer, now=NOW)

    writer.fail_next(operation, fault)
    with pytest.raises(ValueError, match="reconciliar"):
        invoke()
    assert len(pending(conn)) == 1
    calls = len(writer.calls)
    with pytest.raises(ValueError, match="reconciliar"):
        invoke()
    assert len(writer.calls) == calls
    assert reconcile(conn, writer, now=NOW)["alerts"] == []
    assert not pending(conn)
    assert reconcile(conn, writer, now=NOW) == {"resolved": [], "alerts": []}
    invoke()
    effects = len(writer.effects)
    invoke()
    assert len(writer.effects) == effects
    assert len({e["key"] for e in writer.effects}) == effects
    assert len(writer.entities) == len(plan.entities)
    if operation != "create":
        local = Repository(conn, Entity).get(entity.id)
        assert local == writer.read(local.meta_id)
        assert local.status == ("active" if operation == "activate" else "paused")
        if operation == "scale":
            assert local.daily_budget_cents == 2400
    conn.close()


def test_crash_after_creation_restart_then_reconcile(tmp_path):
    conn, plan, approval, directory = setup_launch(tmp_path)
    writer = FakeMeta()
    original = writer.create

    def crash(entity, key):
        result = original(entity, key)
        writer.create = original
        raise KeyboardInterrupt(result)

    writer.create = crash
    with pytest.raises(KeyboardInterrupt):
        execute(conn, plan, approval.id, approval_dir=directory, writer=writer, now=BASE)
    assert pending(conn)[0]["state"] == "orphan"
    conn.close()
    from arb.db import connect

    conn = connect(tmp_path / "db.sqlite")
    assert reconcile(conn, writer, now=NOW)["alerts"] == []
    execute(conn, plan, approval.id, approval_dir=directory, writer=writer, now=BASE)
    assert len(writer.effects) == len(plan.entities)
    assert len(writer.entities) == len(plan.entities)
    conn.close()


def test_reconcile_preserves_divergent_state(tmp_path):
    conn, plan, approval, directory = setup_launch(tmp_path)
    writer = FakeMeta()
    writer.fail_next("create", "after_timeout")
    with pytest.raises(ValueError):
        execute(conn, plan, approval.id, approval_dir=directory, writer=writer, now=BASE)
    entity = next(iter(writer.entities.values()))
    writer.entities[entity.meta_id] = entity.model_copy(update={"geo": "PE"})
    assert reconcile(conn, writer, now=NOW)["alerts"]
    assert pending(conn)
    conn.close()


@pytest.mark.parametrize(
    "case",
    [
        "writer",
        "transaction",
        "stale",
        "read",
        "missing",
        "kind",
        "outside",
        "operation",
        "activation",
        "scale",
        "parent",
    ],
)
def test_planted_authority_and_state_violations(tmp_path, case):
    from arb.remote.journal import authorize, exposure, perform, require_fake

    conn, plan, approval, directory = setup_launch(tmp_path)
    source = plan.entities[0]
    with conn:
        for entity in plan.entities:
            Repository(conn, Entity).add(entity)
    writer = FakeMeta()
    context = plan.model_dump(mode="json")
    with pytest.raises(ValueError):
        if case == "writer":
            require_fake(object())
        elif case == "transaction":
            conn.execute("BEGIN")
            perform(
                conn, writer, source, "create", "k", context=context, approval=approval, now=BASE
            )
        elif case == "stale":
            source = source.model_copy(update={"geo": "PE"})
            # Authority still references the original entity.
            perform(
                conn, writer, source, "create", "k", context=context, approval=approval, now=BASE
            )
        elif case == "read":
            source = source.model_copy(update={"meta_id": "missing"})
            perform(conn, writer, source, "pause", "k", context={}, now=BASE)
        elif case == "missing":
            authorize(conn, "create", source, context, None, BASE)
        elif case == "kind":
            bad = sign(approval.model_copy(update={"kind": "activate"}))
            authorize(conn, "create", source, context, bad, BASE)
        elif case == "outside":
            authorize(
                conn, "create", source.model_copy(update={"id": "other"}), context, approval, BASE
            )
        elif case == "operation":
            authorize(conn, "delete", source, context, approval, BASE)
        elif case == "activation":
            authorize(conn, "activate", source, {}, approval, BASE)
        elif case == "scale":
            authorize(
                conn, "scale", source, {"entity": {}, "to_budget_cents": 999999}, approval, BASE
            )
        else:
            ad = next(e for e in plan.entities if e.kind == "ad").model_copy(
                update={"parent_id": "missing"}
            )
            exposure(conn, ad)
    assert not writer.calls
    conn.rollback()
    conn.close()


@pytest.mark.parametrize(
    "case", ["local_changed", "wrong_ack", "transaction", "unknown_intent", "before_write_race"]
)
def test_reconciliation_does_not_hide_conflict(tmp_path, monkeypatch, case):
    from arb.remote.journal import finish, perform, reconcile_fake

    conn, plan, approval, directory = setup_launch(tmp_path)
    writer = FakeMeta()
    writer.fail_next("create", "after_timeout")
    with pytest.raises(ValueError):
        execute(conn, plan, approval.id, approval_dir=directory, writer=writer, now=BASE)
    attempt = next(a for a in Repository(conn, Action).list() if a.result == "intent")
    source = Entity.model_validate(attempt.payload_json["source"])
    observed = writer.locate(attempt.payload_json["key"])
    if case == "local_changed":
        with conn:
            Repository(conn, Entity).update(source.model_copy(update={"geo": "PE"}))
        assert reconcile_fake(conn, writer, now=NOW)["alerts"]
    elif case == "wrong_ack":
        with pytest.raises(ValueError):
            finish(conn, attempt, observed.model_copy(update={"geo": "PE"}), now=NOW)
    elif case == "transaction":
        conn.execute("BEGIN")
        with pytest.raises(ValueError):
            reconcile_fake(conn, writer, now=NOW)
        conn.rollback()
    elif case == "unknown_intent":
        with conn:
            Repository(conn, Action).add(
                Action(
                    id="foreign",
                    ts=NOW,
                    actor="engine",
                    kind="pause",
                    result="intent",
                    live=False,
                    payload_json={},
                )
            )
        assert reconcile_fake(conn, writer, now=NOW)["alerts"]
    else:
        reconcile_fake(conn, writer, now=NOW)
        # Change the local source between remote read and intent transaction.
        target = observed
        original = writer.read

        def racing_read(identifier):
            result = original(identifier)
            with conn:
                Repository(conn, Entity).update(target.model_copy(update={"geo": "PE"}))
            return result

        monkeypatch.setattr(writer, "read", racing_read)
        with pytest.raises(ValueError, match="estado alterado"):
            perform(conn, writer, target, "pause", "race", context={}, now=NOW)
        assert not conn.in_transaction
    conn.close()


def test_ad_budget_and_replay_key(tmp_path):
    from arb.remote.journal import exposure, perform

    conn, plan, approval, directory = setup_launch(tmp_path)
    writer = FakeMeta()
    execute(conn, plan, approval.id, approval_dir=directory, writer=writer, now=BASE)
    ad = next(e for e in Repository(conn, Entity).list() if e.kind == "ad")
    assert exposure(conn, ad) == 2000
    action = perform(conn, writer, ad, "pause", "same", context={}, now=BASE)
    assert perform(conn, writer, ad, "pause", "same", context={}, now=BASE) == action
    conn.close()
