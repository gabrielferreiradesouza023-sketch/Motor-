from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.launcher import approval as module
from arb.launcher.approval import canonical, sign, sign_file, verify
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
        ("signature", "0" * 64),
    ],
)
def test_every_field_is_authenticated(field, value):
    item = approved()
    changed = Approval.model_validate(item.model_dump() | {field: value})
    with pytest.raises(ValueError, match="inválida"):
        verify(changed)


def test_wrong_missing_key_and_unsigned(monkeypatch):
    item = approved()
    assert canonical(item) == canonical(item.model_copy(update={"signature": None}))
    verify(item)
    monkeypatch.setenv("APPROVAL_SIGNING_KEY", "different-synthetic-fixture")
    with pytest.raises(ValueError, match="inválida"):
        verify(item)
    with pytest.raises(ValueError, match="sem assinatura"):
        verify(item.model_copy(update={"signature": None}))
    monkeypatch.delenv("APPROVAL_SIGNING_KEY")
    with pytest.raises(ValueError, match="ausente"):
        verify(item)
    with pytest.raises(ValueError, match="ausente"):
        sign(item)


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
