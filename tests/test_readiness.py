import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

import arb.readiness as panel
from arb.accept import evidence, save
from arb.cli import app
from arb.permissions import private_directory, private_open

NOW = datetime(2026, 10, 7, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


def write(path, body):
    with private_open(path) as file:
        json.dump(body, file)


def resign(body):
    body.pop("sha256", None)
    body["sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return body


@pytest.fixture
def complete(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    for kind, names in panel.PROOF_CHECKS.items():
        facts = (
            {"graph_version": "v99.0", "spend_cap_cents": 240000}
            if kind == "f5"
            else (
                {"before": "ACTIVE", "after": "PAUSED"}
                if kind == "f6_pause"
                else {"synthetic": True}
            )
        )
        save(
            evidence(kind, [{"name": n, "ok": True} for n in sorted(names)], now=NOW, **facts),
            tmp_path / f"ops/validation/{kind}.json",
        )
    write(
        tmp_path / "ops/validation-status.json",
        {
            "schema": 1,
            "items": {
                name: {
                    "status": "confirmed",
                    "by": "human",
                    "checked_at": NOW.isoformat(),
                    "evidence": "synthetic fixture; never a real provider acceptance",
                }
                for name in panel.HUMAN_ITEMS
            },
        },
    )
    write(tmp_path / "data/backups/drill.json", {"status": "passed", "checked_at": NOW.isoformat()})
    monkeypatch.setattr(
        panel.preflight,
        "inspect",
        lambda **_: {
            "checks": [
                {"name": "meta_spend_cap", "status": "erro"},
                {"name": "card_limit", "status": "ok"},
            ]
        },
    )
    monkeypatch.setattr(panel.service, "check", lambda **_: {"ok": True})
    return tmp_path


def index(result):
    return {row["name"]: row for row in result["items"]}


def test_every_mock_human_evidence_still_cannot_enable_graph(complete):
    result = panel.inspect(root=complete, now=NOW)
    assert result["status"] == "não pronto" and result["ready"] is False
    assert result["pending"] == ["graph_executor"]
    assert all(row["ok"] for row in result["items"] if row["name"] != "graph_executor")
    # A file named like an executor never proves reviewed/implemented Graph capability.
    private_directory(complete / "src/arb/meta")
    (complete / "src/arb/meta/executor.py").write_text("# synthetic placeholder only")
    assert panel.inspect(root=complete, now=NOW) == result


@pytest.mark.parametrize(
    "item",
    [
        "preflight",
        "drill_recent",
        "permissions",
        "approval_public_key",
        "f5",
        "f6_pause",
        "tracking",
        *panel.HUMAN_ITEMS,
        "service_package",
    ],
)
def test_each_item_rejects_planted_violation(complete, monkeypatch, item):
    root = complete
    if item == "preflight":
        monkeypatch.setattr(
            panel.preflight,
            "inspect",
            lambda **_: {"checks": [{"name": "ledger", "status": "erro"}]},
        )
    elif item == "drill_recent":
        write(
            root / "data/backups/drill.json",
            {"status": "passed", "checked_at": (NOW - timedelta(days=3)).isoformat()},
        )
    elif item == "permissions":
        (root / "data").chmod(0o755)
    elif item == "approval_public_key":
        path = root / "config/settings.yaml"
        settings = yaml.safe_load(path.read_text())
        settings["approval_public_key"] = "invalid"
        path.write_text(yaml.safe_dump(settings))
    elif item in panel.PROOF_CHECKS:
        (root / f"ops/validation/{item}.json").unlink()
    elif item in panel.HUMAN_ITEMS:
        path = root / "ops/validation-status.json"
        body = json.loads(path.read_text())
        body["items"][item] = {"status": "pending"}
        write(path, body)
    else:
        monkeypatch.setattr(panel.service, "check", lambda **_: {"ok": False})
    result = panel.inspect(root=root, now=NOW)
    assert not index(result)[item]["ok"] and item in result["pending"]
    assert result["ready"] is False
    assert index(result)[item]["reason"] and index(result)[item]["next_step"]


@pytest.mark.parametrize(
    "violation",
    [
        "hash",
        "future",
        "stale",
        "naive",
        "bad_timestamp",
        "missing_timestamp",
        "schema",
        "kind",
        "status",
        "check_failed",
        "empty_checks",
        "duplicate_checks",
        "cap_zero",
        "cap_high",
        "cap_bool",
        "version",
        "malformed",
        "symlink",
    ],
)
def test_proof_integrity_freshness_and_contract(complete, violation):
    path = complete / "ops/validation/f5.json"
    body = json.loads(path.read_text())
    if violation == "hash":
        body["spend_cap_cents"] = 1  # Change signed content without updating integrity hash.
    elif violation in {"future", "stale", "naive", "bad_timestamp", "missing_timestamp"}:
        body["checked_at"] = {
            "future": (NOW + timedelta(seconds=1)).isoformat(),
            "stale": (NOW - timedelta(days=7, seconds=1)).isoformat(),
            "naive": "2026-10-07T00:00:00",
            "bad_timestamp": "wrong",
            "missing_timestamp": None,
        }[violation]
    elif violation == "schema":
        body["schema"] = True
    elif violation == "kind":
        body["kind"] = "tracking"
    elif violation == "status":
        body["status"] = "failed"
    elif violation == "check_failed":
        body["checks"][0]["ok"] = 1
    elif violation == "empty_checks":
        body["checks"] = []
    elif violation == "duplicate_checks":
        body["checks"].append(body["checks"][0])
    elif violation.startswith("cap_"):
        body["spend_cap_cents"] = {"cap_zero": 0, "cap_high": 240001, "cap_bool": True}[violation]
    elif violation == "version":
        body["graph_version"] = "unknown"
    elif violation == "malformed":
        path.write_text("[]")
        assert not panel.proof(path, "f5", NOW, cap=240000)
        return
    elif violation == "symlink":
        alternate = complete / "f5-copy.json"
        alternate.write_text(path.read_text())
        path.unlink()
        path.symlink_to(alternate)
        assert not panel.proof(path, "f5", NOW, cap=240000)
        return
    write(path, body if violation == "hash" else resign(body))
    assert not panel.proof(path, "f5", NOW, cap=240000)
    assert not index(panel.inspect(root=complete, now=NOW))["f5"]["ok"]


@pytest.mark.parametrize(
    "violation", ["missing", "schema", "names", "malformed", "actor", "date", "reference"]
)
def test_human_registry_does_not_trust_incomplete_confirmation(complete, violation):
    path = complete / "ops/validation-status.json"
    body = json.loads(path.read_text())
    if violation == "missing":
        path.unlink()
    elif violation == "schema":
        body["schema"] = 2
        write(path, body)
    elif violation == "names":
        body["items"].pop("V-01")
        write(path, body)
    elif violation == "malformed":
        path.write_text("null")
    else:
        row = body["items"]["V-01"]
        row[{"actor": "by", "date": "checked_at", "reference": "evidence"}[violation]] = None
        write(path, body)
    assert not panel.confirmations(complete, NOW)["V-01"]


def test_readonly_no_network_private_or_env_reads_and_stable_json(complete, monkeypatch):
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path.name not in {".env", "approval_ed25519", "private.key"}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)

    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden in readiness")

    monkeypatch.setattr(httpx, "Client", no_network)
    first = panel.inspect(root=complete, now=NOW)
    assert json.dumps(first, sort_keys=True) == json.dumps(
        panel.inspect(root=complete, now=NOW), sort_keys=True
    )
    assert first["pending"] == ["graph_executor"]
    result = CliRunner().invoke(app, ["readiness", "--root", str(complete), "--json"])
    assert result.exit_code == 1 and json.loads(result.stdout)["status"] == "não pronto"
    result = CliRunner().invoke(app, ["readiness", "--root", str(complete)])
    assert result.exit_code == 1 and "✘ graph_executor" in result.stdout


def test_missing_local_data_config_symlink_and_exception_paths(tmp_path, complete, monkeypatch):
    empty = panel.inspect(root=tmp_path / "missing", now=NOW)
    assert set(["drill_recent", "preflight", "approval_public_key", "f5", "graph_executor"]) <= set(
        empty["pending"]
    )

    def unavailable(**_):
        raise OSError("synthetic-hidden")

    monkeypatch.setattr(panel.preflight, "inspect", unavailable)
    monkeypatch.setattr(panel.service, "check", unavailable)
    failed = panel.inspect(root=complete, now=NOW)
    assert not index(failed)["preflight"]["ok"] and not index(failed)["service_package"]["ok"]
    # Config link rejected before preflight or reading any sensitive target.
    target = complete / "never-read.txt"
    target.write_text("synthetic sentinel")
    path = complete / "config/settings.yaml"
    path.unlink()
    path.symlink_to(target)
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path != target and path != complete / "config/settings.yaml"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    assert not index(panel.inspect(root=complete, now=NOW))["approval_public_key"]["ok"]
    with pytest.raises(ValueError, match="fuso"):
        panel.inspect(root=complete, now=datetime(2026, 10, 7))


def test_proof_boundary_and_other_kind_failures(complete):
    assert panel.fresh((NOW - timedelta(days=7)).isoformat(), NOW)
    for kind, fact in [("f6_pause", {"after": "ACTIVE"}), ("tracking", {"synthetic": False})]:
        path = complete / f"ops/validation/{kind}.json"
        body = json.loads(path.read_text()) | fact
        write(path, resign(body))
        assert not panel.proof(path, kind, NOW, cap=240000)
    path = complete / "data/backups/drill.json"
    path.unlink()
    assert not index(panel.inspect(root=complete, now=NOW))["drill_recent"]["ok"]
