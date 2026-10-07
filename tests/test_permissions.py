import os
import stat

import pytest
from test_doctor import clean_root as _clean_root
from test_execute import setup_launch
from test_preflight import configured as _configured

from arb.analyst.report import generate_report
from arb.db import backup_daily, connect, migrate
from arb.db.restore import restore_new
from arb.doctor import diagnose
from arb.permissions import inspect_paths, private_directory, private_open, reject_links
from arb.preflight import inspect

clean_root = _clean_root
configured = _configured


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_database_backup_restore_report_closed_under_open_umask(tmp_path):
    previous = os.umask(0)
    try:
        path = tmp_path / "data/engine.db"
        conn = connect(path)
        migrate(conn)
        backup = backup_daily(conn, path.parent / "backups")
        recovered = restore_new(backup, tmp_path / "restore/new.db")
        report = generate_report(conn, tmp_path / "reports")
        assert all(
            mode(p) == 0o600
            for p in (path, backup, recovered, report, report.parent / "latest.html")
        )
        assert all(
            mode(p) == 0o700 for p in (path.parent, backup.parent, recovered.parent, report.parent)
        )
        assert inspect_paths(tmp_path)["ok"]
        conn.close()
    finally:
        os.umask(previous)


@pytest.mark.parametrize("directory", ["data", "data/backups", "ops/approvals/approved", "reports"])
def test_open_modes_warn_doctor_block_preflight(clean_root, directory):
    path = clean_root / directory
    private_directory(path)
    file = path / "sample"
    with private_open(file) as output:
        output.write("financial sentinel")
    file.chmod(0o644)
    path.chmod(0o755)
    findings = inspect_paths(clean_root)["findings"]
    assert any(row["kind"] == "mode" for row in findings)
    errors, warnings = diagnose(clean_root)
    assert not errors and any("Permissão" in row for row in warnings)
    checks = inspect(root=clean_root)["checks"]
    assert next(row for row in checks if row["name"] == "permissions")["status"] == "erro"


@pytest.mark.parametrize("location", ["data", "reports", "ops/approvals/approved"])
def test_symlink_rejected_without_reading_target(clean_root, tmp_path, location):
    target = tmp_path / "target"
    target.mkdir()
    path = clean_root / location
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target, target_is_directory=True)
    assert not inspect_paths(clean_root)["ok"]
    errors, _ = diagnose(clean_root)
    assert errors and any("symlink" in row for row in errors)
    with pytest.raises(ValueError, match="symlink"):
        private_open(path / "secret")
    assert not (target / "secret").exists()


def test_nested_link_and_empty_marker(tmp_path):
    data = tmp_path / "data"
    private_directory(data)
    (data / ".gitkeep").touch()
    assert inspect_paths(tmp_path)["ok"]
    (data / "linked").symlink_to(tmp_path)
    assert not inspect_paths(tmp_path)["ok"]
    with pytest.raises(ValueError, match="symlink"):
        reject_links(data / "linked/child")


def test_windows_reports_acl_warning_without_mode_false_error(tmp_path, monkeypatch):
    import arb.permissions as permissions

    data = tmp_path / "data"
    data.mkdir()
    (data / "sample").write_text("synthetic")
    monkeypatch.setattr(permissions, "posix", lambda: False)
    assert inspect_paths(tmp_path)["ok"]
    assert "ACL" in inspect_paths(tmp_path)["warnings"][0]
    with private_open(data / "new") as file:
        file.write("synthetic")
    private_directory(data)


def test_private_publication_exclusive_append_and_file_parent(tmp_path):
    path = tmp_path / "private/nested/file"
    with private_open(path, exclusive=True) as file:
        file.write("one")
    with pytest.raises(FileExistsError):
        private_open(path, exclusive=True)
    with private_open(path, append=True) as file:
        file.write("two")
    assert path.read_text() == "onetwo" and mode(path) == 0o600
    with pytest.raises(ValueError, match="diretório"):
        private_directory(path)


def test_descriptor_closed_on_wrapping_failure(tmp_path, monkeypatch):
    import arb.permissions as permissions

    original = permissions.os.fdopen

    def fail(*args, **kwargs):
        raise OSError("planted wrapper failure")

    monkeypatch.setattr(permissions.os, "fdopen", fail)
    with pytest.raises(OSError, match="wrapper"):
        private_open(tmp_path / "file")
    monkeypatch.setattr(permissions.os, "fdopen", original)


def test_approved_file_closed(tmp_path, monkeypatch):
    conn, _, approval, directory = setup_launch(tmp_path)
    import arb.launcher.approval as module

    monkeypatch.setattr(module, "is_interactive", lambda: True)
    pending = directory.parent / "pending"
    pending.mkdir()
    approval = approval.model_copy(update={"id": "permissions-approved"})
    source = pending / (approval.id + ".json")
    source.write_text(
        approval.model_copy(
            update={"status": "pending", "signature": None, "decided_at": None}
        ).model_dump_json()
    )
    target = module.sign_file(source, lambda _: True)
    assert mode(target) == 0o600 and mode(target.parent) == 0o700
    conn.close()


def test_custom_database_paths_inspected(tmp_path):
    directory = tmp_path / "custom"
    private_directory(directory)
    with private_open(directory / "engine.db") as file:
        file.write("synthetic")
    assert inspect_paths(tmp_path / "root", database=directory / "engine.db")["ok"]
    (directory / "engine.db").chmod(0o644)
    assert not inspect_paths(tmp_path / "root", database=directory / "engine.db")["ok"]


def test_daily_backup_does_not_delete_another_writer_temporary(tmp_path):
    from datetime import date

    conn = connect(tmp_path / "data/engine.db")
    migrate(conn)
    directory = tmp_path / "data/backups"
    private_directory(directory)
    temporary = directory / "engine-2026-10-07.tmp"
    with private_open(temporary) as file:
        file.write("another writer sentinel")
    with pytest.raises(FileExistsError):
        backup_daily(conn, directory, day=date(2026, 10, 7))
    assert temporary.read_text() == "another writer sentinel"
    conn.close()
