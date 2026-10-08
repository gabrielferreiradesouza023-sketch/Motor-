import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from arb import accept
from arb.cli import app
from arb.launcher import approval
from arb.readiness import inspect


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "f5.json"
    accept.save(
        accept.evidence("f5", [{"name": "example", "ok": True}], now=datetime.now(UTC)), path
    )
    return path


def test_signature_valid_and_hash_preserved(document, monkeypatch):
    unsigned = json.loads(document.read_text())
    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    signed = accept.sign_evidence(document, lambda message: "f5" in message)
    assert accept.verify_evidence(document) == unsigned | {"signature": signed["signature"]}
    assert document.stat().st_mode & 0o777 == 0o600
    assert CliRunner().invoke(app, ["evidence", "verify", str(document)]).exit_code == 0
    with pytest.raises(ValueError, match="já assinada"):
        accept.sign_evidence(document, lambda _: True)


@pytest.mark.parametrize("mutation", ["unsigned", "field", "signature", "other_key", "hash"])
def test_forgery_rejected(document, monkeypatch, mutation):
    body = approval.sign_document(json.loads(document.read_text()))
    if mutation == "unsigned":
        body.pop("signature")
    elif mutation == "field":
        body["injected"] = "fabricated"
        unsigned = {k: v for k, v in body.items() if k not in {"signature", "sha256"}}
        import hashlib

        body["sha256"] = hashlib.sha256(approval.canonical_document(unsigned)).hexdigest()
    elif mutation == "signature":
        body["signature"] = 7
    elif mutation == "hash":
        body["sha256"] = "0" * 64
    else:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        monkeypatch.setattr(
            approval,
            "configured_public_key",
            lambda _: Ed25519PublicKey.from_public_bytes(bytes(32)),
        )
    document.write_text(json.dumps(body))
    assert CliRunner().invoke(app, ["evidence", "verify", str(document)]).exit_code == 1


@pytest.mark.parametrize("failure", ["tty", "private", "cancel", "kind", "link", "json"])
def test_sign_failures_leave_source_untouched(document, monkeypatch, failure):
    monkeypatch.setattr(approval, "is_interactive", lambda: failure != "tty")
    if failure == "private":
        monkeypatch.delenv("APPROVAL_PRIVATE_KEY_FILE")
    if failure == "kind":
        document.write_text("{}")
    if failure == "json":
        document.write_text("[")
    if failure == "link":
        link = document.parent / "link.json"
        link.symlink_to(document)
        document = link
    original = document.read_text()
    with pytest.raises(ValueError):
        accept.sign_evidence(document, lambda _: failure != "cancel")
    assert document.read_text() == original
    assert CliRunner().invoke(app, ["evidence", "sign", str(document)]).exit_code == 1


def test_concurrent_change_refused(document):
    with pytest.raises(ValueError, match="mudou"):
        accept.replace_document(document, {}, "old content")


def test_unsigned_readiness_reason_and_no_private_read(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    shutil.copytree(Path(__file__).resolve().parents[1] / "config", tmp_path / "config")
    accept.save(accept.evidence("f5", []), tmp_path / "ops/validation/f5.json")
    monkeypatch.setattr(
        approval, "_private_key", lambda: pytest.fail("read-only must never read private")
    )
    row = next(r for r in inspect(root=tmp_path)["items"] if r["name"] == "f5")
    assert row["ok"] is False and row["reason"] == "evidência não assinada"
