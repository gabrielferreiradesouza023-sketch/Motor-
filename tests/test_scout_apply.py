import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.creative import generate_angles
from arb.creative.copy import generate_copies
from arb.db import Repository, connect, migrate
from arb.launcher import plan
from arb.launcher.approval import read_document, sign, sign_file
from arb.models import Action, Offer
from arb.scout import import_adlibrary, import_offers
from arb.scout.approve import apply
from arb.scout.ranking import propose, rank

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 7, tzinfo=UTC)


def setup_scout(tmp_path, monkeypatch):
    import arb.launcher.approval as module

    monkeypatch.setattr(module, "is_interactive", lambda: True)
    conn = connect(tmp_path / "scout.db")
    migrate(conn)
    ranked, _ = rank(
        import_offers(ROOT / "examples/scout/offers.csv"),
        import_adlibrary(ROOT / "examples/scout/adlibrary.csv"),
    )
    path = propose(conn, ranked, tmp_path / "pending")
    signed = sign_file(path, lambda _: True, now=NOW)
    approval, _ = read_document(signed)
    return conn, approval, signed


def test_signed_offers_apply_and_launch_eligibility(tmp_path, monkeypatch):
    conn, approval, path = setup_scout(tmp_path, monkeypatch)
    action = apply(conn, approval.id, directory=path.parent, now=NOW)
    assert apply(conn, approval.id, directory=path.parent, now=NOW) == action
    assert len(Repository(conn, Action).list()) == 1
    offers = Repository(conn, Offer).list()
    assert all(o.status == "approved" for o in offers)
    offer = offers[0]
    angles = [a.model_copy(update={"status": "approved"}) for a in generate_angles(offer, [])[:1]]
    creatives = [
        c.model_copy(update={"status": "approved"})
        for c in generate_copies(offer, angles[0], region="CO")
    ]
    assert (
        plan(
            offer,
            angles,
            creatives,
            geo="CO",
            daily_budget_cents=3000,
            destination_url="https://bridge.example",
        ).offer
        == offer
    )
    result = CliRunner().invoke(app, ["approve", "verify", str(path)])
    assert result.exit_code == 0
    assert read_document(path)[1]["kind"] == "new_offer"
    conn.close()


@pytest.mark.parametrize(
    "case",
    ["tamper", "changed", "kind", "missing_plan", "duplicate", "transaction", "symlink", "bad_id"],
)
def test_offer_violations_refused(tmp_path, monkeypatch, case):
    conn, approval, path = setup_scout(tmp_path, monkeypatch)
    document = json.loads(path.read_text())
    if case == "tamper":
        document["plan"]["offers"][0]["name"] = "altered"
        path.write_text(json.dumps(document))
    elif case == "changed":
        with conn:
            offer = Repository(conn, Offer).list()[0]
            offer.commission_brl_cents += 1
            Repository(conn, Offer).update(offer)
    elif case == "kind":
        document["approval"]["kind"] = "launch"
        path.write_text(json.dumps(document))
    elif case == "missing_plan":
        path.write_text(approval.model_dump_json())
    elif case == "duplicate":
        document["plan"]["offers"].append(document["plan"]["offers"][0])
        digest = hashlib.sha256(
            json.dumps(
                document["plan"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        document["approval"] = sign(approval.model_copy(update={"plan_hash": digest})).model_dump(
            mode="json"
        )
        path.write_text(json.dumps(document))
    elif case == "transaction":
        conn.execute("BEGIN")
    elif case == "symlink":
        moved = path.with_suffix(".original")
        path.rename(moved)
        path.symlink_to(moved)
    identifier = "../invalid" if case == "bad_id" else approval.id
    with pytest.raises(ValueError):
        apply(conn, identifier, directory=path.parent, now=NOW)
    conn.rollback()
    assert all(o.status == "candidate" for o in Repository(conn, Offer).list())
    assert Repository(conn, Action).list() == []
    conn.close()


def test_plan_kind_mismatch_and_empty_offers(tmp_path, monkeypatch):
    conn, approval, path = setup_scout(tmp_path, monkeypatch)
    document = json.loads(path.read_text())
    document["plan"]["kind"] = "wrong"
    digest = hashlib.sha256(
        json.dumps(
            document["plan"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    document["approval"] = sign(approval.model_copy(update={"plan_hash": digest})).model_dump(
        mode="json"
    )
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="diverge"):
        read_document(path)
    document["plan"] = {"kind": "new_offer", "offers": []}
    digest = hashlib.sha256(
        json.dumps(
            document["plan"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    document["approval"] = sign(approval.model_copy(update={"plan_hash": digest})).model_dump(
        mode="json"
    )
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="ausentes"):
        apply(conn, approval.id, directory=path.parent, now=NOW)
    conn.close()
