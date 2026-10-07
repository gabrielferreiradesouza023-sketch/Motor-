import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from test_execute import setup_launch

from arb.db import Repository
from arb.db.checkpoint import backup_directory
from arb.launcher.approval import read_document, sign_file
from arb.launcher.execute import execute
from arb.launcher.scale import apply, last_increase, propose
from arb.models import Action, Entity

BASE = datetime(2026, 10, 5, tzinfo=UTC)
NOW = BASE + timedelta(hours=24)


def seeded(tmp_path, monkeypatch):
    import arb.launcher.approval as module

    monkeypatch.setattr(module, "is_interactive", lambda: True)
    conn, plan, approval, directory = setup_launch(tmp_path)
    execute(conn, plan, approval.id, approval_dir=directory, output=tmp_path / "out", now=BASE)
    entity = next(e for e in plan.entities if e.kind == "adset")
    return conn, entity


def approved_scale(conn, entity, tmp_path):
    path = propose(
        conn,
        entity.id,
        entity.daily_budget_cents * 120 // 100,
        directory=tmp_path / "pending",
        now=NOW,
    )
    signed = sign_file(path, lambda _: True, now=NOW)
    approval, _ = read_document(signed)
    return approval, signed


def test_exact_borders_and_one_consumption(tmp_path, monkeypatch):
    conn, entity = seeded(tmp_path, monkeypatch)
    approval, path = approved_scale(conn, entity, tmp_path)
    assert approval.max_exposure_cents == entity.daily_budget_cents * 120 // 100
    action = apply(conn, approval.id, directory=path.parent, now=NOW)
    after = Repository(conn, Entity).get(entity.id)
    assert after.daily_budget_cents == entity.daily_budget_cents * 120 // 100
    assert last_increase(conn, entity.id) == NOW
    assert apply(conn, approval.id, directory=path.parent, now=NOW + timedelta(days=3)) == action
    assert sum(a.kind == "scale" for a in Repository(conn, Action).list()) == 1
    backup = next(backup_directory(conn).glob("pre-scale-*.db"))
    with sqlite3.connect(backup) as snapshot:
        assert (
            Repository(snapshot, Entity).get(entity.id).daily_budget_cents
            == entity.daily_budget_cents
        )
    conn.close()


@pytest.mark.parametrize(
    "delta,budget,allowed",
    [
        (timedelta(hours=24), 2400, True),
        (timedelta(hours=24) - timedelta(microseconds=1), 2400, False),
        (timedelta(hours=24), 2401, False),
        (timedelta(hours=24), 2000, False),
        (timedelta(hours=24), True, False),
    ],
)
def test_scale_reference_limits(tmp_path, monkeypatch, delta, budget, allowed):
    conn, entity = seeded(tmp_path, monkeypatch)
    assert entity.daily_budget_cents == 2000
    if allowed:
        path = propose(conn, entity.id, budget, directory=tmp_path / "pending", now=BASE + delta)
        assert propose(conn, entity.id, budget, directory=path.parent, now=BASE + delta) == path
        path.write_text("planted conflict")
        with pytest.raises(ValueError, match="divergente"):
            propose(conn, entity.id, budget, directory=path.parent, now=BASE + delta)
    else:
        with pytest.raises(ValueError):
            propose(conn, entity.id, budget, directory=tmp_path / "pending", now=BASE + delta)
        assert not (tmp_path / "pending").exists()
    conn.close()


@pytest.mark.parametrize(
    "case",
    [
        "tamper",
        "changed",
        "quarantine",
        "pending",
        "plain",
        "symlink",
        "id",
        "transaction",
        "recent_increase",
    ],
)
def test_scale_refuses_violations(tmp_path, monkeypatch, case):
    conn, entity = seeded(tmp_path, monkeypatch)
    approval, path = approved_scale(conn, entity, tmp_path)
    if case == "tamper":
        document = json.loads(path.read_text())
        document["approval"]["max_exposure_cents"] += 1
        path.write_text(json.dumps(document))
    elif case == "changed":
        with conn:
            changed = Repository(conn, Entity).get(entity.id)
            changed.geo = "PE"
            Repository(conn, Entity).update(changed)
    elif case == "quarantine":
        with conn:
            conn.execute(
                "INSERT INTO restore_quarantine VALUES(?,?,?,?,NULL)",
                ("q", "synthetic", "a" * 64, NOW.isoformat()),
            )
    elif case == "pending":
        with conn:
            Repository(conn, Action).add(
                Action(
                    id="orphan",
                    ts=NOW,
                    actor="engine",
                    kind="pause",
                    payload_json={"entity_id": entity.id},
                    live=False,
                    result="intent",
                )
            )
    elif case == "plain":
        path.write_text(approval.model_dump_json())
    elif case == "symlink":
        other = path.with_suffix(".original")
        path.rename(other)
        path.symlink_to(other)
    elif case == "transaction":
        conn.execute("BEGIN")
    elif case == "recent_increase":
        with conn:
            Repository(conn, Action).add(
                Action(
                    id="other-scale",
                    ts=NOW - timedelta(hours=1),
                    actor="engine",
                    kind="scale",
                    payload_json={"entity_id": entity.id},
                    live=False,
                    result="simulated",
                )
            )
    with pytest.raises(ValueError):
        apply(conn, "../bad" if case == "id" else approval.id, directory=path.parent, now=NOW)
    conn.rollback()
    assert Repository(conn, Entity).get(entity.id).daily_budget_cents == entity.daily_budget_cents
    conn.close()


def test_backup_failure_and_state_race_abort(tmp_path, monkeypatch):
    import arb.launcher.scale as module

    conn, entity = seeded(tmp_path, monkeypatch)
    approval, path = approved_scale(conn, entity, tmp_path)
    original = module.snapshot_before

    def fail(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(module, "snapshot_before", fail)
    with pytest.raises(OSError):
        apply(conn, approval.id, directory=path.parent, now=NOW)
    assert Repository(conn, Entity).get(entity.id).daily_budget_cents == entity.daily_budget_cents

    def race(*args):
        result = original(*args)
        with conn:
            changed = Repository(conn, Entity).get(entity.id)
            changed.geo = "PE"
            Repository(conn, Entity).update(changed)
        return result

    monkeypatch.setattr(module, "snapshot_before", race)
    with pytest.raises(ValueError, match="durante"):
        apply(conn, approval.id, directory=path.parent, now=NOW)
    assert not conn.in_transaction
    assert Repository(conn, Entity).get(entity.id).daily_budget_cents == entity.daily_budget_cents
    conn.close()


def test_unknown_entity_and_transaction_proposal(tmp_path, monkeypatch):
    conn, entity = seeded(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        propose(conn, "missing", 100, now=NOW)
    conn.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        propose(conn, entity.id, 2400, now=NOW)
    conn.rollback()
    conn.close()
