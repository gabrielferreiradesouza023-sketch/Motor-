import ast
import inspect
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from arb import doctor, hostinfo, preflight, readiness
from arb.cli import app


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    (tmp_path / "1").mkdir()
    (tmp_path / "version").write_text("Linux native")
    (tmp_path / "1/comm").write_text("systemd\n")
    (tmp_path / "timezone").write_text("America/Sao_Paulo\n")
    monkeypatch.setattr(hostinfo.shutil, "which", lambda _: "/fake/systemctl")
    return tmp_path


def report(host):
    return hostinfo.inspect(proc=host, timezone=host / "timezone")


@pytest.mark.parametrize(
    "wsl,systemd", [(False, True), (False, False), (True, True), (True, False)]
)
def test_platform_units_and_readonly_command_reference(host, monkeypatch, wsl, systemd):
    (host / "version").write_text("Linux Microsoft-standard-WSL2" if wsl else "Linux native")
    (host / "1/comm").write_text("systemd" if systemd else "init")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "timeout": 2,
            "check": False,
            "shell": False,
        }
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "ActiveState=active\nUnitFileState=enabled\n"
                "NextElapseUSecRealtime=Thu 2026-10-08 00:10:00 UTC\n"
            ),
        )

    monkeypatch.setattr(hostinfo.subprocess, "run", run)
    result = report(host)
    assert result["wsl"] == wsl and result["systemd_pid1"] == systemd
    assert result["timezone"] == "America/Sao_Paulo"
    assert calls == [
        ["/fake/systemctl", "show", name, "-p", "ActiveState,UnitFileState,NextElapseUSecRealtime"]
        for name in hostinfo.NAMES
    ]
    assert all(r["installed"] and r["active"] and r["available"] for r in result["units"])
    assert ("WSL sem systemd" in result["warnings"]) == (wsl and not systemd)
    assert len(result["warnings"]) == (2 if wsl and not systemd else 1 if wsl else 0)


@pytest.mark.parametrize(
    "failure",
    [
        "absent",
        "command",
        "timeout",
        "oserror",
        "exit",
        "malformed",
        "bad_active",
        "bad_state",
        "bad_timer",
    ],
)
def test_missing_or_invalid_units_reported_without_raw_error(host, monkeypatch, failure):
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("synthetic", 2)
        if failure == "oserror":
            raise OSError("synthetic-private-error")
        if failure == "exit":
            return SimpleNamespace(returncode=1, stdout="", stderr="synthetic-private-error")
        if failure == "malformed":
            return SimpleNamespace(returncode=0, stdout="nonsense")
        return SimpleNamespace(
            returncode=0,
            stdout=(
                f"ActiveState={'garbage' if failure == 'bad_active' else 'inactive'}\n"
                f"UnitFileState={'garbage' if failure == 'bad_state' else ''}\n"
                f"NextElapseUSecRealtime={'a' * 161 if failure == 'bad_timer' else ''}\n"
            ),
        )

    monkeypatch.setattr(hostinfo.subprocess, "run", run)
    if failure == "command":
        monkeypatch.setattr(hostinfo.shutil, "which", lambda _: None)
    result = report(host)
    assert all(not r["installed"] and not r["active"] for r in result["units"])
    assert all(r["available"] == (failure == "absent") for r in result["units"])
    assert "synthetic-private-error" not in json.dumps(result)


def test_environment_detection_and_timezone_fallback(host, monkeypatch):
    (host / "version").unlink()
    (host / "1/comm").unlink()
    (host / "timezone").unlink()
    monkeypatch.setenv("WSL_DISTRO_NAME", "Synthetic")
    monkeypatch.setattr(hostinfo.shutil, "which", lambda _: None)
    monkeypatch.setattr(Path, "readlink", lambda _: Path("/usr/share/zoneinfo/Etc/UTC"))
    assert report(host)["wsl"] and report(host)["timezone"] == "Etc/UTC"

    def unavailable(_):
        raise OSError("absent")

    monkeypatch.setattr(Path, "readlink", unavailable)
    assert report(host)["timezone"] == "desconhecido"


def test_static_subprocess_only_show_and_no_state_verbs():
    tree = ast.parse(inspect.getsource(hostinfo))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
    ]
    assert len(calls) == 1 and isinstance(calls[0].args[0], ast.List)
    assert calls[0].args[0].elts[1].value == "show"
    forbidden = {"start", "stop", "enable", "disable", "restart", "daemon-reload"}
    assert not any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in forbidden
        for n in ast.walk(tree)
    )


def test_cli_reference_and_warning_propagation(host, monkeypatch):
    monkeypatch.setattr(hostinfo.shutil, "which", lambda _: None)
    (host / "version").write_text("Linux Microsoft")
    (host / "1/comm").write_text("init")
    snapshot = report(host)
    monkeypatch.setattr(hostinfo, "inspect", lambda: snapshot)
    runner = CliRunner()
    assert json.loads(runner.invoke(app, ["service", "status", "--json"]).output) == snapshot
    assert "WSL sem systemd" in runner.invoke(app, ["service", "status"]).output
    root = Path(__file__).resolve().parents[1]
    assert set(snapshot["warnings"]) <= set(doctor.diagnose(root)[1])
    check = next(
        c for c in preflight.inspect(root=root)["checks"] if c["name"] == "host_diagnostic"
    )
    assert check["status"] == "aviso"
    panel = readiness.inspect(root=root)
    assert panel["host"] == snapshot
    assert not next(r for r in panel["items"] if r["name"] == "persistent_host")["ok"]
