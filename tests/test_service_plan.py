import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb import hostinfo, service
from arb.cli import app
from arb.permissions import private_open

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    for path in (tmp_path / "data/engine.db.scheduler.lock", tmp_path / ".venv/bin/arb"):
        with private_open(path) as file:
            file.write("synthetic")
    (tmp_path / ".venv/bin/arb").chmod(0o700)
    monkeypatch.setattr(hostinfo, "is_wsl", lambda: False)
    output = tmp_path / "units"
    service.render(tmp_path, "arbuser", output=output)
    return tmp_path, output


def test_plan_reference_snapshot_deterministic_and_no_subprocess(package, monkeypatch):
    root, output = package

    def forbidden(*a, **kw):
        raise AssertionError("no subprocess may be executed")

    monkeypatch.setattr(subprocess, "run", forbidden)
    plan = service.install_plan(output=output)
    reference = (Path(__file__).parent / "fixtures/service-plan-linux.txt").read_text()
    assert plan.replace(str(root), "<ROOT>") == reference
    assert plan == service.install_plan(output=output)
    assert (
        CliRunner().invoke(app, ["service", "install-plan", "--output", str(output)]).output == plan
    )


@pytest.mark.parametrize("damage", ["hash", "unit", "missing", "schema", "symlink", "mode"])
def test_tampered_package_never_emits_plan(package, damage):
    _, output = package
    path = output / "manifest.json"
    if damage in ["hash", "schema"]:
        body = json.loads(path.read_text())
        if damage == "hash":
            body["sha256"]["arb-scheduler.service"] = "0" * 64
        else:
            body["schema"] = 99
        path.write_text(json.dumps(body))
    elif damage == "unit":
        (output / "arb-scheduler.service").write_text("forged")
    elif damage == "missing":
        (output / "arb-backup.timer").unlink()
    elif damage == "mode":
        path.chmod(0o644)
    else:
        target = path.with_suffix(".original")
        path.rename(target)
        path.symlink_to(target)
    result = CliRunner().invoke(app, ["service", "install-plan", "--output", str(output)])
    assert result.exit_code == 1 and "sudo install" not in result.output


def test_failed_check_and_manifest_race_refused(package, monkeypatch):
    _, output = package
    monkeypatch.setattr(
        service, "check", lambda **_: {"ok": False, "errors": ["synthetic check failure"]}
    )
    with pytest.raises(ValueError, match="recusado"):
        service.install_plan(output=output)

    def changed(**_):
        path = output / "manifest.json"
        body = json.loads(path.read_text())
        body["user"] = "changed"
        path.write_text(json.dumps(body))
        return {"ok": True}

    monkeypatch.setattr(service, "check", changed)
    with pytest.raises(ValueError, match="mudou"):
        service.install_plan(output=output)


def test_wsl_boot_steps_and_quoted_output_path(package, monkeypatch):
    root, output = package
    quoted = root / "units with ' quote; chars"
    output.rename(quoted)
    monkeypatch.setattr(hostinfo, "is_wsl", lambda: True)

    def forbidden(*a, **kw):
        raise AssertionError("no subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    plan = service.install_plan(output=quoted)
    assert "# [boot]\n# systemd=true\nsudoedit /etc/wsl.conf\n" in plan
    assert "# wsl --shutdown\n" in plan
    import shlex

    line = next(line for line in plan.splitlines() if line.startswith("sudo install"))
    assert shlex.split(line) == [
        "sudo",
        "install",
        "-m",
        "0644",
        "--",
        str(quoted / "arb-scheduler.service"),
        "/etc/systemd/system/arb-scheduler.service",
    ]
    assert not (root / "ops/validation-status.json").exists()
