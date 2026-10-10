"""Synthetic observation readiness: each rejection plants a real missing prerequisite."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

import arb.readiness as panel
from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.launcher.approval import sign_document
from arb.models import Offer
from arb.smoke import register
from arb.validation import HUMAN_ITEMS

NOW = datetime(2026, 10, 10, tzinfo=UTC)


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture
def observe_root(tmp_path, records, monkeypatch):
    root = tmp_path
    (root / "config").mkdir()
    for name in ("settings.yaml", "rules.yaml"):
        (root / "config" / name).write_bytes((Path("config") / name).read_bytes())
    conn = connect(root / "data/engine.db")
    migrate(conn)
    with conn:
        Repository(conn, Offer).add(
            records[0].model_copy(
                update={
                    "producer_paid_traffic_ok": True,
                    "evidence_ref": "SYNTHETIC written permission",
                }
            )
        )
    register(conn, "1", "2", ["3"], "offer", "CO", 25000, now=NOW)
    conn.close()
    (root / "ops").mkdir()
    (root / "ops/validation-status.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "items": {
                    name: sign_document(
                        {
                            "kind": "human_validation",
                            "item": name,
                            "status": "confirmed",
                            "by": "human",
                            "checked_at": NOW.isoformat(),
                            "evidence": "SYNTHETIC external setting verified",
                        }
                    )
                    for name in HUMAN_ITEMS
                },
            }
        )
    )
    (root / "data/backups").mkdir()
    (root / "data/backups/drill.json").write_text(
        json.dumps({"status": "passed", "checked_at": NOW.isoformat()})
    )
    for name in ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID", "META_API_VERSION"):
        monkeypatch.setenv(name, "SYNTHETIC_PRIVATE_SENTINEL_" + name)
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setattr(panel, "datetime", Frozen)
    return root


def test_ready_observe_without_network_or_secret_output(observe_root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("readiness must never reach HTTP")

    monkeypatch.setattr(httpx, "Client", forbidden)
    original = Path.read_text

    def read(path, *args, **kwargs):
        assert path.name not in {".env", "approval_ed25519"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    result = CliRunner().invoke(
        app, ["readiness", "--root", str(observe_root), "--scope", "observe", "--json"]
    )
    assert result.exit_code == 0, result.exception
    data = json.loads(result.stdout)
    assert data["ready"] and data["pending"] == []
    assert data["authorizes"] == "nenhuma escrita; somente leitura da fumaça humana"
    assert {"graph_executor", "f5", "f6_pause", "tracking", "V-03", "service_installed"} <= {
        r["item"] for r in data["not_required_for_observe"]
    }
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in result.output
    before = (observe_root / "data/engine.db").read_bytes()
    text = CliRunner().invoke(app, ["readiness", "--root", str(observe_root), "--scope", "observe"])
    assert text.exit_code == 0 and "somente leitura" in text.stdout
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in text.output
    assert (observe_root / "data/engine.db").read_bytes() == before


@pytest.mark.parametrize(
    "violation,item",
    [
        ("live", "live_mode"),
        ("invalid_live", "live_mode"),
        ("database", "database"),
        ("migration", "database"),
        ("checksum", "database"),
        ("drill", "drill_recent"),
        ("drill_missing", "drill_recent"),
        ("card_limit", "card_limit"),
        ("spend_cap", "spend_cap"),
        ("stale_record", "card_limit"),
        ("unsigned", "spend_cap"),
        ("env", "meta_read_env"),
        ("smoke", "smoke_registered"),
        ("cap", "smoke_registered"),
        ("permission", "smoke_offer_permission"),
        ("evidence", "smoke_offer_permission"),
        ("database_link", "database"),
        ("config_link", "database"),
    ],
)
def test_observe_rejects_each_planted_violation(observe_root, monkeypatch, violation, item):
    root = observe_root
    if violation == "live":
        # Transport explicitly mocked; readiness never invokes it.
        monkeypatch.setattr(
            httpx, "Client", lambda: httpx.MockTransport(lambda _: httpx.Response(200))
        )
        monkeypatch.setenv("LIVE_MODE", "true")
    elif violation == "invalid_live":
        monkeypatch.setenv("LIVE_MODE", "invalid")
    elif violation == "env":
        monkeypatch.delenv("META_API_VERSION")
    elif violation in {"card_limit", "spend_cap", "stale_record", "unsigned"}:
        path = root / "ops/validation-status.json"
        registry = json.loads(path.read_text())
        name = (
            "card_limit"
            if violation == "stale_record"
            else "spend_cap"
            if violation == "unsigned"
            else violation
        )
        row = registry["items"][name]
        if violation == "stale_record":
            row.pop("signature")
            row["checked_at"] = (NOW - timedelta(days=7, seconds=1)).isoformat()
            registry["items"][name] = sign_document(row)
        elif violation == "unsigned":
            row.pop("signature")
        else:
            registry["items"][name] = {"status": "pending"}
        path.write_text(json.dumps(registry))
    elif violation.startswith("drill"):
        path = root / "data/backups/drill.json"
        if violation == "drill_missing":
            path.unlink()
        else:
            path.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "checked_at": (NOW - timedelta(hours=48, seconds=1)).isoformat(),
                    }
                )
            )
    elif violation in {"config_link", "database_link"}:
        path = root / ("config/rules.yaml" if violation == "config_link" else "data/engine.db")
        target = root / "linked"
        path.rename(target)
        path.symlink_to(target)
    elif violation == "database":
        (root / "data/engine.db").unlink()
    else:
        conn = connect(root / "data/engine.db")
        with conn:
            if violation == "migration":
                conn.execute("DELETE FROM schema_migrations WHERE version=11")
            elif violation == "checksum":
                conn.execute("UPDATE schema_migrations SET checksum='bad' WHERE version=11")
            elif violation == "smoke":
                conn.execute("DELETE FROM smoke_entities")
                conn.execute("DELETE FROM smoke_campaigns")
            elif violation == "cap":
                conn.execute("UPDATE smoke_campaigns SET cap_cents=999999")
            else:
                offer = Repository(conn, Offer).get("offer")
                if violation == "permission":
                    offer.producer_paid_traffic_ok = False
                else:
                    offer.evidence_ref = "   "
                Repository(conn, Offer).update(offer)
        conn.close()
    result = CliRunner().invoke(
        app, ["readiness", "--root", str(root), "--scope", "observe", "--json"]
    )
    assert result.exit_code == 1, result.exception
    data = json.loads(result.stdout)
    assert not data["ready"] and item in {r["item"] for r in data["pending"]}
    assert "SYNTHETIC_PRIVATE_SENTINEL" not in result.output


def test_observe_boundaries_and_invalid_scope(observe_root, monkeypatch):
    root = observe_root
    monkeypatch.delenv("LIVE_MODE")
    (root / "data/backups/drill.json").write_text(
        json.dumps({"status": "passed", "checked_at": (NOW - timedelta(hours=48)).isoformat()})
    )
    assert panel.inspect_observe(root=root, now=NOW)["ready"]
    with pytest.raises(ValueError, match="fuso"):
        panel.inspect_observe(root=root, now=NOW.replace(tzinfo=None))
    assert CliRunner().invoke(app, ["readiness", "--scope", "invalid"]).exit_code == 2


@pytest.mark.parametrize("flags,reference", [([], "full.txt"), (["--json"], "full.json")])
def test_default_full_output_matches_pre_batch_reference(monkeypatch, flags, reference):
    monkeypatch.setattr(panel, "datetime", Frozen)
    monkeypatch.setattr(panel.hostinfo, "inspect", lambda: {"host": "synthetic reference"})
    result = CliRunner().invoke(
        app, ["readiness", "--root", "tests/fixtures/readiness/absent", *flags]
    )
    assert result.exit_code == 1
    assert result.stdout == (Path("tests/fixtures/readiness") / reference).read_text()
