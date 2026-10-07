import hashlib
import json
from datetime import UTC, datetime

import pytest
from test_scout_apply import setup_scout

from arb.creative import generate_angles
from arb.creative.approve import apply, propose
from arb.creative.copy import generate_copies
from arb.db import Repository
from arb.launcher import plan
from arb.launcher.approval import read_document, sign, sign_file
from arb.models import Action, Angle, Creative, Offer
from arb.scout.approve import apply as approve_offers

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def setup_creatives(tmp_path, monkeypatch):
    conn, approval, path = setup_scout(tmp_path, monkeypatch)
    approve_offers(conn, approval.id, directory=path.parent, now=NOW)
    offer = Repository(conn, Offer).list()[0]
    angles = generate_angles(offer, [])[:1]
    creatives = generate_copies(offer, angles[0], region="CO")
    with conn:
        for record in [*angles, *creatives]:
            Repository(conn, type(record)).add(record)
    return conn, offer, angles, creatives


def test_signed_creative_set_to_launch_plan(tmp_path, monkeypatch):
    conn, offer, angles, creatives = setup_creatives(tmp_path, monkeypatch)
    path = propose(conn, offer.id, directory=tmp_path / "pending")
    assert propose(conn, offer.id, directory=path.parent) == path
    signed = sign_file(path, lambda _: True, now=NOW)
    approval, _ = read_document(signed)
    action = apply(conn, approval.id, directory=signed.parent, now=NOW)
    assert apply(conn, approval.id, directory=signed.parent, now=NOW) == action
    approved_angles = Repository(conn, Angle).list()
    approved_creatives = Repository(conn, Creative).list()
    assert all(c.status == "approved" for c in approved_creatives)
    assert plan(
        offer,
        approved_angles,
        approved_creatives,
        geo="CO",
        daily_budget_cents=3000,
        destination_url="https://bridge.example",
    ).entities
    assert sum(a.kind == "creative_set_apply" for a in Repository(conn, Action).list()) == 1
    conn.close()


@pytest.mark.parametrize("case", ["bad_lint", "fresh_lint"])
def test_lint_failed_never_proposed(tmp_path, monkeypatch, case):
    conn, offer, angles, creatives = setup_creatives(tmp_path, monkeypatch)
    with conn:
        bad = creatives[0]
        if case == "bad_lint":
            bad.policy_lint = "failed"
        else:
            bad.headline = "Cura garantizada"
        Repository(conn, Creative).update(bad)
    path = propose(conn, offer.id, directory=tmp_path / "pending")
    _, document = read_document(path)
    assert bad.id not in {c["id"] for c in document["creatives"]}
    conn.close()


@pytest.mark.parametrize(
    "case",
    [
        "tamper",
        "changed",
        "angle_changed",
        "duplicate",
        "no_angle",
        "invalid_lint",
        "plain",
        "transaction",
        "symlink",
        "bad_id",
    ],
)
def test_creative_violations_fail_closed(tmp_path, monkeypatch, case):
    conn, offer, angles, creatives = setup_creatives(tmp_path, monkeypatch)
    path = propose(conn, offer.id, directory=tmp_path / "pending")
    signed = sign_file(path, lambda _: True, now=NOW)
    approval, document = read_document(signed)
    if case in {"changed", "angle_changed"}:
        record = creatives[0] if case == "changed" else angles[0]
        with conn:
            if case == "changed":
                record.headline = "Texto alterado"
            else:
                record.hypothesis = "Hipótese alterada"
            Repository(conn, type(record)).update(record)
    elif case == "plain":
        signed.write_text(approval.model_dump_json())
    elif case == "transaction":
        conn.execute("BEGIN")
    elif case == "symlink":
        other = signed.with_suffix(".original")
        signed.rename(other)
        signed.symlink_to(other)
    elif case in {"tamper", "duplicate", "no_angle", "invalid_lint"}:
        if case == "tamper":
            document["creatives"][0]["headline"] = "Texto adulterado"
        elif case == "duplicate":
            document["creatives"].append(document["creatives"][0])
        elif case == "no_angle":
            document["creatives"][0]["angle_id"] = "missing"
        else:
            document["creatives"][0]["policy_lint"] = "failed"
        if case != "tamper":
            digest = hashlib.sha256(
                json.dumps(
                    document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
            approval = sign(approval.model_copy(update={"plan_hash": digest}))
        signed.write_text(
            json.dumps({"approval": approval.model_dump(mode="json"), "plan": document})
        )
    with pytest.raises(ValueError):
        apply(conn, "../bad" if case == "bad_id" else approval.id, directory=signed.parent, now=NOW)
    conn.rollback()
    assert all(c.status == "candidate" for c in Repository(conn, Creative).list())
    assert not any(a.kind == "creative_set_apply" for a in Repository(conn, Action).list())
    conn.close()


def test_empty_unapproved_and_conflicting_proposals(tmp_path, monkeypatch):
    conn, offer, angles, creatives = setup_creatives(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="new_offer"):
        propose(conn, "missing", directory=tmp_path / "pending")
    path = propose(conn, offer.id, directory=tmp_path / "pending")
    path.write_text("planted conflict")
    with pytest.raises(ValueError, match="divergente"):
        propose(conn, offer.id, directory=path.parent)
    with conn:
        for creative in creatives:
            creative.policy_lint = "failed"
            Repository(conn, Creative).update(creative)
    with pytest.raises(ValueError, match="nenhum"):
        propose(conn, offer.id, directory=path.parent)
    conn.close()
