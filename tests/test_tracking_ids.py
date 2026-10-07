from pathlib import Path

import pytest
from test_bridge import CONTENT
from test_tracker import tracking_db as _tracking_db

from arb.bridge import build
from arb.db import Repository
from arb.models import Entity, SaleEvent
from arb.tracker import entity_map, ingest
from arb.tracker.ids import tracking_id, validate

tracking_db = _tracking_db


def test_roundtrip_replay_full_and_short(tracking_db, records):
    with tracking_db:
        token = tracking_id(tracking_db, "entity", max_length=3)
        assert tracking_id(tracking_db, "entity", max_length=3) == token
        assert ingest(tracking_db, records[5].model_copy(update={"tracking_param": token}))
    assert len(token) == 3
    assert entity_map(tracking_db)[token] == "entity"
    assert Repository(tracking_db, SaleEvent).list()[0].matched_entity_id == "entity"
    assert tracking_id(tracking_db, "entity") == "entity"
    assert tracking_id(tracking_db, "entity", max_length=10) == "entity"
    with tracking_db:
        e = Repository(tracking_db, Entity).get("entity")
        e.meta_id = "123456789"
        Repository(tracking_db, Entity).update(e)
    assert tracking_id(tracking_db, "entity") == "123456789"
    assert entity_map(tracking_db)[token] == "entity"
    with pytest.raises(ValueError, match="desconhecida"):
        tracking_id(tracking_db, "unknown")


@pytest.mark.parametrize("collision", ["short", "full"])
def test_collision_is_explicit(tracking_db, records, monkeypatch, collision):
    import arb.tracker.ids as module

    monkeypatch.setattr(module, "candidate", lambda *args: "abc")
    with tracking_db:
        tracking_id(tracking_db, "entity", max_length=3)
        other = records[3].model_copy(
            update={"id": "another", "meta_id": "abc" if collision == "full" else None}
        )
        Repository(tracking_db, Entity).add(other)
        with pytest.raises(ValueError, match="colisão"):
            tracking_id(tracking_db, "another", max_length=3)
    if collision == "full":
        with pytest.raises(ValueError, match="ambíguo"):
            entity_map(tracking_db)


@pytest.mark.parametrize(
    "length,alphabet", [(0, "ab"), (129, "ab"), (True, "ab"), (3, "aa"), (3, "a!"), (3, "")]
)
def test_invalid_configuration(length, alphabet):
    with pytest.raises(ValueError):
        validate(length, alphabet)


def test_bridge_disabled_identical_and_enabled_bound(tracking_db, tmp_path, records):
    args = dict(worker_url="https://worker.example", pixel_id="123", tracking_key="sck")
    old = build(records[0], CONTENT, "old", output=tmp_path, **args).read_bytes()
    disabled = build(
        records[0], CONTENT, "disabled", output=tmp_path, connection=tracking_db, **args
    ).read_bytes()
    assert old == disabled
    assert disabled == (Path(__file__).parent / "fixtures/bridge-default-t61.html").read_bytes()
    page = build(
        records[0],
        CONTENT,
        "short",
        output=tmp_path,
        connection=tracking_db,
        tracking_id_max_length=3,
        **args,
    ).read_text()
    assert "set(config.tracking,config.trackingAliases[ad])" in page
    assert "kind,ad_id:ad" in page
    assert "Boolean(config.trackingAliases[ad])" in page
    assert entity_map(tracking_db)[tracking_id(tracking_db, "entity", max_length=3)] == "entity"
    with pytest.raises(ValueError, match="banco"):
        build(records[0], CONTENT, "bad", output=tmp_path, tracking_id_max_length=3, **args)


def test_collision_with_existing_full_id(tracking_db, records, monkeypatch):
    import arb.tracker.ids as module

    with tracking_db:
        Repository(tracking_db, Entity).add(records[3].model_copy(update={"id": "abc"}))
    monkeypatch.setattr(module, "candidate", lambda *args: "abc")
    with pytest.raises(ValueError, match="colisão"):
        tracking_id(tracking_db, "entity", max_length=3)


def test_bridge_refuses_ambiguous_full_aliases_atomically(tracking_db, records, tmp_path):
    with tracking_db:
        first = Repository(tracking_db, Entity).get("entity")
        first.meta_id = "123456789"
        Repository(tracking_db, Entity).update(first)
        Repository(tracking_db, Entity).add(
            records[3].model_copy(update={"id": "another", "meta_id": "123456789"})
        )
    with pytest.raises(ValueError, match="ambíguo"):
        build(
            records[0],
            CONTENT,
            "bad",
            output=tmp_path,
            worker_url="https://worker.example",
            pixel_id="123",
            tracking_key="sck",
            connection=tracking_db,
            tracking_id_max_length=3,
        )
    assert tracking_db.execute("SELECT count(*) FROM tracking_ids").fetchone()[0] == 0
