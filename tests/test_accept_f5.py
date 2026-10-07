import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from arb.accept import evidence, f5, save, suffix
from arb.cli import app
from arb.meta.read import Reader

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 7, tzinfo=UTC)


@pytest.fixture
def root(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    return tmp_path


def mock_reader(fault=None):
    calls = []

    def handler(request):
        assert request.method == "GET"
        calls.append(request)
        if (
            fault in ("currency", "timezone")
            and "spend_cap" not in request.url.params.get("fields", "")
            and not request.url.path.endswith(("/ads", "/insights"))
        ):
            return httpx.Response(
                200,
                json={
                    "currency": "USD" if fault == "currency" else "BRL",
                    "timezone_name": "UTC" if fault == "timezone" else "America/Sao_Paulo",
                },
            )
        if fault == "token":
            return httpx.Response(400, json={"error": {"code": 190, "message": "synthetic-hidden"}})
        if fault == "network":
            raise httpx.ReadTimeout("synthetic-hidden")
        if request.url.path.endswith("/insights"):
            return httpx.Response(403 if fault == "insights" else 200, json={"data": []})
        if request.url.path.endswith("/ads"):
            return httpx.Response(
                403 if fault == "ads" else 200,
                json={"data": [{"id": "987654321", "name": "synthetic-hidden"}]},
            )
        return httpx.Response(
            200,
            json={
                "id": "act_123456789",
                "currency": "BRL",
                "timezone_name": "America/Sao_Paulo",
                "spend_cap": 0
                if fault == "cap_zero"
                else 240001
                if fault == "cap_high"
                else True
                if fault == "cap_bool"
                else "240000",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return (
        Reader("synthetic-hidden", "123456789", "v99.0", client=client, attempts=1),
        client,
        calls,
    )


@pytest.mark.parametrize(
    "fault,failed",
    [
        (None, None),
        ("currency", "account_brl_sao_paulo"),
        ("timezone", "account_brl_sao_paulo"),
        ("insights", "insights_read"),
        ("ads", "ads_read"),
        ("token", "account_brl_sao_paulo"),
        ("network", "account_brl_sao_paulo"),
        ("cap_zero", "spend_cap"),
        ("cap_high", "spend_cap"),
        ("cap_bool", "spend_cap"),
    ],
)
def test_f5_matrix_get_only_redaction(root, monkeypatch, fault, failed):
    monkeypatch.setenv("LIVE_MODE", "true")
    reader, client, calls = mock_reader(fault)
    with client:
        result = f5(reader, root=root, now=NOW)
    assert result["status"] == ("passed" if failed is None else "failed")
    if failed:
        assert not next(c for c in result["checks"] if c["name"] == failed)["ok"]
    raw = json.dumps(result)
    assert "synthetic-hidden" not in raw and "123456789" not in raw and "987654321" not in raw
    assert all(call.method == "GET" for call in calls)
    body = {k: v for k, v in result.items() if k != "sha256"}
    assert (
        result["sha256"]
        == hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    assert result["graph_version"] == "v99.0"


def test_false_mode_no_get_and_cli(root, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "false")
    reader, client, calls = mock_reader()
    with client, pytest.raises(ValueError, match="host humano"):
        f5(reader, root=root)
    assert calls == []
    result = CliRunner().invoke(
        app, ["accept", "f5", "--root", str(root), "--out", str(root / "proof.json")]
    )
    assert result.exit_code == 1 and not (root / "proof.json").exists()


def test_permissions_block_network(root, monkeypatch):
    monkeypatch.setenv("LIVE_MODE", "true")
    (root / "data").mkdir(mode=0o755)
    (root / "data").chmod(0o755)
    reader, client, calls = mock_reader()
    with client:
        assert f5(reader, root=root, now=NOW)["status"] == "failed"
    assert calls == []


def test_cli_proof_saved_closed_and_failure_exit(root, monkeypatch):
    import arb.preflight as preflight

    monkeypatch.setenv("LIVE_MODE", "true")
    reader, client, _ = mock_reader("cap_zero")
    monkeypatch.setattr(preflight, "make_reader", lambda _: reader)
    with client:
        result = CliRunner().invoke(
            app, ["accept", "f5", "--root", str(root), "--out", str(root / "proof.json")]
        )
    assert result.exit_code == 1
    assert json.loads((root / "proof.json").read_text())["status"] == "failed"
    assert (root / "proof.json").stat().st_mode & 0o077 == 0


def test_evidence_naive_and_no_overwrite(root):
    with pytest.raises(ValueError, match="fuso"):
        evidence("f5", [], now=datetime(2026, 10, 7))
    proof = evidence("f5", [], now=NOW)
    save(proof, root / "proof.json")
    with pytest.raises(FileExistsError):
        save(proof, root / "proof.json")
    assert suffix("123") == "[redigido]" and suffix("act_123456") == "…3456"
