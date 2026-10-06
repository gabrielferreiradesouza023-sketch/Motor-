from datetime import UTC, datetime

import pytest
from conftest import REAL_CONFIGURED_PUBLIC_KEY, SYNTHETIC_PUBLIC_HEX
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from typer.testing import CliRunner

from arb.cli import app
from arb.launcher import approval as module
from arb.launcher.approval import canonical, keygen, sign, sign_file, verify
from arb.models import Approval


def approved():
    return sign(
        Approval(
            id="fixture",
            kind="launch",
            plan_hash="a" * 64,
            summary="Teste sintético",
            max_exposure_cents=6000,
            status="approved",
            decided_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("plan_hash", "b" * 64),
        ("kind", "scale"),
        ("summary", "alterado"),
        ("max_exposure_cents", 6001),
        ("status", "rejected"),
        ("decided_at", datetime(2026, 1, 2, tzinfo=UTC)),
        ("signature", "0" * 128),
    ],
)
def test_every_field_is_authenticated(field, value):
    item = approved()
    changed = Approval.model_validate(item.model_dump() | {field: value})
    with pytest.raises(ValueError, match="inválida"):
        verify(changed)


def test_wrong_missing_key_and_unsigned(monkeypatch, tmp_path):
    item = approved()
    assert canonical(item) == canonical(item.model_copy(update={"signature": None}))
    verify(item)
    with pytest.raises(ValueError, match="sem assinatura"):
        verify(item.model_copy(update={"signature": None}))
    # Outra chave pública versionada: assinatura antiga deixa de valer.
    other = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    monkeypatch.setattr(module, "configured_public_key", lambda settings=None: other.public_key())
    with pytest.raises(ValueError, match="inválida"):
        verify(item)
    # Chave privada que não corresponde à pública versionada não assina.
    with pytest.raises(ValueError, match="não corresponde"):
        sign(item)
    monkeypatch.delenv("APPROVAL_PRIVATE_KEY_FILE")
    with pytest.raises(ValueError, match="ausente"):
        sign(item)


def test_verifier_cannot_sign(monkeypatch):
    """ADR-022: quem só tem a chave pública (motor/agentes) não consegue assinar."""
    unsigned = approved().model_copy(update={"signature": None})
    monkeypatch.delenv("APPROVAL_PRIVATE_KEY_FILE")
    with pytest.raises(ValueError, match="ausente"):
        sign(unsigned)
    forged = unsigned.model_copy(update={"signature": "ab" * 64})
    with pytest.raises(ValueError, match="inválida"):
        verify(forged)


def test_settings_public_key_fail_closed(tmp_path, monkeypatch):
    item = approved()
    monkeypatch.setattr(module, "configured_public_key", REAL_CONFIGURED_PUBLIC_KEY)
    settings = tmp_path / "settings.yaml"
    for content in ["approval_public_key: null\n", "approval_public_key: zz\n", "x: [", "bad"]:
        settings.write_text(content)
        with pytest.raises(ValueError, match="approval_public_key"):
            verify(item, settings=settings)
    settings.write_text(f"approval_public_key: {SYNTHETIC_PUBLIC_HEX}\n")
    verify(item, settings=settings)
    with pytest.raises(ValueError, match="approval_public_key"):
        verify(item, settings=tmp_path / "missing.yaml")


def test_private_key_file_guards(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text("ff" * 32)
    key.chmod(0o644)
    monkeypatch.setenv("APPROVAL_PRIVATE_KEY_FILE", str(key))
    with pytest.raises(ValueError, match="permissão"):
        sign(approved())
    key.chmod(0o600)
    key.write_text("not-hex")
    with pytest.raises(ValueError, match="inválido"):
        sign(approved())
    monkeypatch.setenv("APPROVAL_PRIVATE_KEY_FILE", str(tmp_path / "absent"))
    with pytest.raises(ValueError, match="ausente"):
        sign(approved())


def test_keygen_outside_repo_only(tmp_path, monkeypatch):
    unsigned = approved().model_copy(update={"signature": None})
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="repositório"):
        keygen(repo / "config" / "key", repo)
    destination = tmp_path / "home" / ".arb" / "approval_ed25519"
    public = keygen(destination, repo)
    assert len(public) == 64 and oct(destination.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):
        keygen(destination, repo)
    monkeypatch.setenv("APPROVAL_PRIVATE_KEY_FILE", str(destination))
    settings = tmp_path / "settings.yaml"
    settings.write_text(f"approval_public_key: {public}\n")
    monkeypatch.setattr(module, "configured_public_key", REAL_CONFIGURED_PUBLIC_KEY)
    item = sign(unsigned, settings=settings)
    verify(item, settings=settings)


def test_keygen_cli_requires_tty(tmp_path):
    result = CliRunner().invoke(app, ["approve", "keygen", "--output", str(tmp_path / "k")])
    assert result.exit_code != 0 and "tty" in result.output
    assert not (tmp_path / "k").exists()


def pending(tmp_path):
    path = tmp_path / "pending" / "fixture.json"
    path.parent.mkdir()
    item = approved().model_copy(
        update={"status": "pending", "decided_at": None, "signature": None}
    )
    path.write_text(item.model_dump_json())
    return path


def test_cli_refuses_non_tty(tmp_path):
    source = pending(tmp_path)
    result = CliRunner().invoke(app, ["approve", "sign", str(source)], input="y\n")
    assert result.exit_code != 0 and "tty" in result.output
    assert source.exists() and not (tmp_path / "approved").exists()


def test_human_confirmation_sign_verify(tmp_path, monkeypatch):
    source = pending(tmp_path)
    monkeypatch.setattr(module, "is_interactive", lambda: True)
    now = datetime(2026, 1, 2, tzinfo=UTC)
    prompts = []
    destination = sign_file(source, lambda text: prompts.append(text) or True, now=now)
    assert not source.exists()
    assert all(word in prompts[0] for word in ["kind=launch", "6000", "a" * 64])
    item = Approval.model_validate_json(destination.read_text())
    verify(item)
    assert item.status == "approved" and item.decided_at == now
    result = CliRunner().invoke(app, ["approve", "verify", str(destination)])
    assert result.exit_code == 0
    item.max_exposure_cents += 1
    destination.write_text(item.model_dump_json())
    assert CliRunner().invoke(app, ["approve", "verify", str(destination)]).exit_code != 0


def test_cancellation_and_no_overwrite(tmp_path, monkeypatch):
    source = pending(tmp_path)
    monkeypatch.setattr(module, "is_interactive", lambda: True)
    with pytest.raises(ValueError, match="cancelada"):
        sign_file(source, lambda _: False)
    assert source.exists()
    dest = tmp_path / "approved" / source.name
    dest.parent.mkdir()
    dest.write_text("preserve")
    with pytest.raises(FileExistsError):
        sign_file(source, lambda _: True)
    assert dest.read_text() == "preserve" and source.exists()


def test_consumer_rejects_unsigned_even_matching_plan(tmp_path):
    from test_execute import setup_launch

    from arb.launcher.execute import execute

    conn, value, item, directory = setup_launch(tmp_path)
    try:
        item.signature = None
        (directory / "human.json").write_text(item.model_dump_json())
        with pytest.raises(ValueError, match="sem assinatura"):
            execute(conn, value, item.id, approval_dir=directory)
    finally:
        conn.close()
