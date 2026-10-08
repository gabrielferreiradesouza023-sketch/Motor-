import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb import validation
from arb.cli import app
from arb.launcher import approval
from arb.readiness import confirmations

NOW = datetime(2026, 10, 7, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    (tmp_path / "ops").mkdir()
    shutil.copyfile(ROOT / "ops/validation-status.json", tmp_path / "ops/validation-status.json")
    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    return tmp_path


def test_signed_record_changes_only_one_item_and_show_is_readonly(registry, monkeypatch):
    before = json.loads((registry / "ops/validation-status.json").read_text())
    row = validation.record("V-01", "referência sintética", lambda _: True, root=registry, now=NOW)
    after = json.loads((registry / "ops/validation-status.json").read_text())
    assert after["items"]["V-01"] == row
    assert {k: v for k, v in after["items"].items() if k != "V-01"} == {
        k: v for k, v in before["items"].items() if k != "V-01"
    }
    monkeypatch.setattr(approval, "_private_key", lambda: pytest.fail("private read"))
    assert [n for n, ok in confirmations(registry, NOW).items() if ok] == ["V-01"]
    assert validation.show(root=registry, now=NOW)["V-01"] == {"valid": True, "status": "confirmed"}
    assert not validation.show(root=registry, now=NOW)["V-02"]["valid"]
    assert (registry / "ops/validation-status.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "mutation",
    [
        "unsigned",
        "copy",
        "edit",
        "future",
        "old",
        "naive",
        "empty",
        "evidence_type",
        "actor",
        "status",
        "kind",
        "row_type",
        "signature",
        "link",
    ],
)
def test_planted_forgery_or_invalid_record_rejected(registry, mutation):
    row = validation.record("V-01", "synthetic", lambda _: True, root=registry, now=NOW)
    item = "V-01"
    if mutation == "unsigned":
        row.pop("signature")
    elif mutation == "copy":
        item = "V-02"
    elif mutation == "edit":
        row["evidence"] = "forged"
    elif mutation in ["future", "old", "naive"]:
        row["checked_at"] = (
            NOW + timedelta(days=1)
            if mutation == "future"
            else NOW - timedelta(days=8)
            if mutation == "old"
            else NOW.replace(tzinfo=None)
        ).isoformat()
        row = approval.sign_document(row)
    elif mutation in ["empty", "evidence_type", "actor", "status", "kind"]:
        field = {
            "empty": "evidence",
            "evidence_type": "evidence",
            "actor": "by",
            "status": "status",
            "kind": "kind",
        }[mutation]
        row[field] = 7 if mutation == "evidence_type" else " " if mutation == "empty" else "forged"
        row = approval.sign_document(row)
    elif mutation == "row_type":
        row = []
    elif mutation == "signature":
        row["signature"] = "0" * 128
    else:
        settings = registry / "config/settings.yaml"
        settings.rename(settings.with_suffix(".original"))
        settings.symlink_to(settings.with_suffix(".original"))
    assert not validation.valid_record(item, row, NOW, settings=registry / "config/settings.yaml")


@pytest.mark.parametrize("failure", ["unknown", "tty", "empty", "private", "cancel", "naive"])
def test_record_failures_do_not_modify_registry(registry, monkeypatch, failure):
    original = (registry / "ops/validation-status.json").read_text()
    if failure == "tty":
        monkeypatch.setattr(approval, "is_interactive", lambda: False)
    if failure == "private":
        monkeypatch.delenv("APPROVAL_PRIVATE_KEY_FILE")
    with pytest.raises(ValueError):
        validation.record(
            "unknown" if failure == "unknown" else "V-01",
            " " if failure == "empty" else "synthetic",
            lambda _: failure != "cancel",
            root=registry,
            now=NOW.replace(tzinfo=None) if failure == "naive" else NOW,
        )
    assert (registry / "ops/validation-status.json").read_text() == original


@pytest.mark.parametrize(
    "body",
    ["[]", '{"schema":true,"items":{}}', '{"schema":1,"items":[]}', '{"schema":1,"items":{}}', "["],
)
def test_malformed_registry_fail_closed(registry, body):
    (registry / "ops/validation-status.json").write_text(body)
    assert not any(confirmations(registry, NOW).values())
    result = CliRunner().invoke(app, ["validate", "show", "--root", str(registry), "--json"])
    assert result.exit_code == 1


def test_cli_success_failure_and_pending_compatibility(registry):
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "show", "--root", str(registry), "--json"])
    assert result.exit_code == 0 and all(
        r["status"] == "pending" for r in json.loads(result.output).values()
    )
    assert (
        runner.invoke(
            app,
            ["validate", "record", "unknown", "--evidence", "synthetic", "--root", str(registry)],
        ).exit_code
        == 1
    )
    assert (
        runner.invoke(
            app,
            ["validate", "record", "V-01", "--evidence", "synthetic", "--root", str(registry)],
            input="y\n",
        ).exit_code
        == 0
    )
    assert "✔ V-01" in runner.invoke(app, ["validate", "show", "--root", str(registry)]).output
    with pytest.raises(ValueError, match="fuso"):
        validation.show(root=registry, now=NOW.replace(tzinfo=None))


def test_manual_confirmed_text_and_copy_do_not_unlock(registry):
    path = registry / "ops/validation-status.json"
    doc = json.loads(path.read_text())
    doc["items"]["V-01"] = {
        "status": "confirmed",
        "by": "human",
        "checked_at": NOW.isoformat(),
        "evidence": "fabricated",
    }
    path.write_text(json.dumps(doc))
    assert not any(confirmations(registry, NOW).values())
    row = validation.record("V-01", "synthetic", lambda _: True, root=registry, now=NOW)
    doc = json.loads(path.read_text())
    doc["items"]["V-02"] = row
    path.write_text(json.dumps(doc))
    assert confirmations(registry, NOW)["V-01"] and not confirmations(registry, NOW)["V-02"]
    row["item"] = "V-02"
    assert not validation.valid_record("V-02", row, NOW)
