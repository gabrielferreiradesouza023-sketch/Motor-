import fcntl
import json
import shutil
from datetime import UTC, date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.permissions import private_directory, private_open
from arb.scheduler import schedule
from arb.service import NAMES, check, render

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def host(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    for path in (tmp_path / "data/engine.db.scheduler.lock", tmp_path / ".venv/bin/arb"):
        with private_open(path) as file:
            file.write("synthetic")
    (tmp_path / ".venv/bin/arb").chmod(0o700)
    return tmp_path


def test_render_reference_determinism_no_subprocess_or_secrets(host, monkeypatch):
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess"))
    )
    output = host / "units"
    first = render(host, "arbuser", output=output)
    before = {name: (output / name).read_bytes() for name in NAMES}
    assert render(host, "arbuser", output=output) == first
    assert before == {name: (output / name).read_bytes() for name in NAMES}
    timer = (output / "arb-scheduler.timer").read_text()
    assert timer == (
        "[Unit]\nDescription=arb scheduled cycles\n[Timer]\n"
        "OnCalendar=*-*-* 09:00:00 America/Sao_Paulo\n"
        "OnCalendar=*-*-* 18:00:00 America/Sao_Paulo\n"
        "OnCalendar=*-*-* 23:30:00 America/Sao_Paulo\n"
        "Persistent=true\nUnit=arb-scheduler.service\n[Install]\n"
        "WantedBy=timers.target\n"
    )
    for name in NAMES:
        text = (output / name).read_text()
        assert "synthetic" not in text
        if name.endswith(".service"):
            assert "EnvironmentFile=-/etc/arb/runtime.env" in text
            assert "ExecStart=/usr/bin/env LIVE_MODE=false" in text
            assert "UMask=0077" in text and "ProtectSystem=strict" in text
    assert check(output=output)["ok"]
    assert [
        s.astimezone(UTC).strftime("%H:%M") for s in schedule(date(2026, 10, 7), date(2026, 10, 7))
    ] == ["12:00", "21:00", "02:30"]


@pytest.mark.parametrize(
    "damage",
    [
        "unit",
        "manifest",
        "mode",
        "lock",
        "executable",
        "permissions",
        "symlink",
        "executable_mode",
        "output_mode",
    ],
)
def test_check_detects_violation(host, damage):
    output = host / "units"
    render(host, "arbuser", output=output)
    if damage == "unit":
        file = output / "arb-scheduler.service"
        file.write_text(file.read_text().replace("LIVE_MODE=false", "LIVE_MODE=true"))
    elif damage == "manifest":
        (output / "manifest.json").write_text("{}")
    elif damage == "mode":
        (output / "arb-backup.service").chmod(0o644)
    elif damage == "lock":
        (host / "data/engine.db.scheduler.lock").unlink()
    elif damage == "executable":
        (host / ".venv/bin/arb").unlink()
    elif damage == "executable_mode":
        (host / ".venv/bin/arb").chmod(0o600)
    elif damage == "output_mode":
        output.chmod(0o755)
    elif damage == "permissions":
        (host / "data").chmod(0o755)
    else:
        file = output / "arb-drill.service"
        file.unlink()
        file.symlink_to(output / "arb-backup.service")
    assert not check(output=output)["ok"]


@pytest.mark.parametrize("user", ["bad user", "root\nExecStart=bad", "../root"])
def test_invalid_user_refused(host, user):
    with pytest.raises(ValueError):
        render(host, user, output=host / "units")


def test_lock_busy_and_cli(host):
    output = host / "units"
    result = CliRunner().invoke(
        app,
        ["service", "render", "--root", str(host), "--user", "arbuser", "--output", str(output)],
    )
    assert result.exit_code == 0
    with (host / "data/engine.db.scheduler.lock").open("rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not check(output=output)["ok"]
    result = CliRunner().invoke(app, ["service", "check", "--output", str(output), "--json"])
    assert result.exit_code == 0 and json.loads(result.stdout)["ok"]
    assert not check(output=host / "missing")["ok"]


def test_service_backup_cli_preserves_symlink_rejection(host):
    from arb.db import connect, migrate

    conn = connect(host / "data/engine.db")
    migrate(conn)
    conn.close()
    outside = host / "outside"
    private_directory(outside)
    (host / "data/backups").symlink_to(outside, target_is_directory=True)
    result = CliRunner().invoke(
        app,
        [
            "db",
            "backup",
            "--database",
            str(host / "data/engine.db"),
            "--output",
            str(host / "data/backups"),
        ],
    )
    assert result.exit_code == 1
    assert list(outside.iterdir()) == []


def test_preflight_with_invalid_financial_path_never_opens_target(host, monkeypatch):
    import arb.preflight as preflight

    target = host / "sensitive-sentinel"
    target.write_text("synthetic sentinel, not a key")
    (host / "data/engine.db").symlink_to(target)
    calls = []

    def spy(*args, **kwargs):
        calls.append(args[0])
        raise AssertionError("financial symlink must not be opened")

    monkeypatch.setattr(preflight.sqlite3, "connect", spy)
    result = preflight.inspect(root=host, database=host / "data/engine.db")
    assert not result["ok"]
    assert calls == []
