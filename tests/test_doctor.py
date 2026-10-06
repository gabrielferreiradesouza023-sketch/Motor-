import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.doctor import INTEGRATION_VARIABLES


@pytest.fixture
def clean_root(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    for directory in ["config", "contracts"]:
        shutil.copytree(source / directory, tmp_path / directory)
    monkeypatch.delenv("LIVE_MODE", raising=False)
    for name in INTEGRATION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def run(root):
    return CliRunner().invoke(app, ["doctor", "--root", str(root)])


def test_clean_doctor_initializes_once_and_warns(clean_root):
    result = run(clean_root)
    assert result.exit_code == 0, result.output
    assert "Doctor OK" in result.output
    assert all(name in result.output for name in INTEGRATION_VARIABLES)
    assert (clean_root / "data/engine.db").exists()
    assert run(clean_root).exit_code == 0


@pytest.mark.parametrize("mode", ["true", "1", "yes", "", "garbage"])
def test_unsafe_or_invalid_mode_refused_before_side_effects(clean_root, monkeypatch, mode):
    monkeypatch.setenv("LIVE_MODE", mode)
    result = run(clean_root)
    assert result.exit_code == 1
    assert "LIVE_MODE" in result.output
    assert not (clean_root / "data").exists()


@pytest.mark.parametrize(
    "file,old,new",
    [
        ("rules", "min_impressions: 1000", "min_impressions: 0"),
        ("rules", "pass_ctr_link: 0.012", "pass_ctr_link: 0.001"),
        ("rules", "total_cap_cents: 240000", "total_cap_cents: 1000"),
        ("settings", "America/Sao_Paulo", "invalid/timezone"),
        ("settings", '"09:00"', '"25:00"'),
        ("settings", "refund_rate: 0.15", "refund_rate: 1.5"),
        ("policy", "forbidden_niches: [saude", "forbidden_niches: [ingles"),
    ],
)
def test_invalid_configuration(clean_root, file, old, new):
    path = clean_root / "config" / f"{file}.yaml"
    path.write_text(path.read_text().replace(old, new))
    result = run(clean_root)
    assert result.exit_code == 1
    assert "Configuração" in result.output


@pytest.mark.parametrize("kind", ["missing", "drift", "invalid"])
def test_bad_contract(clean_root, kind):
    path = clean_root / "contracts/offer.json"
    if kind == "missing":
        path.unlink()
    else:
        path.write_text("{}" if kind == "drift" else "not json")
    assert run(clean_root).exit_code == 1


@pytest.mark.parametrize("kind", ["corrupt", "migration", "table", "trigger", "payload", "fk"])
def test_bad_database(clean_root, kind):
    assert run(clean_root).exit_code == 0
    path = clean_root / "data/engine.db"
    if kind == "corrupt":
        path.write_bytes(b"bad sqlite")
    else:
        with sqlite3.connect(path) as connection:
            if kind == "migration":
                connection.execute("UPDATE schema_migrations SET checksum='bad'")
            elif kind == "table":
                connection.execute("DROP TABLE offers")
            elif kind == "trigger":
                connection.execute("DROP TRIGGER snapshots_no_update")
            elif kind == "payload":
                connection.execute("INSERT INTO offers VALUES ('bad', '{}')")
            elif kind == "fk":
                connection.execute("INSERT INTO angles VALUES ('bad', 'missing', '{}')")
    result = run(clean_root)
    assert result.exit_code == 1
    assert "Banco inválido" in result.output


def test_no_env_read_or_secret_output(clean_root, monkeypatch):
    secret = "local-value-never-display"  # pragma: allowlist secret (synthetic test fixture)
    (clean_root / ".env").write_text("LIVE_MODE=true\nMETA_ACCESS_TOKEN=" + secret)
    monkeypatch.setenv("META_ACCESS_TOKEN", secret)
    result = run(clean_root)
    assert result.exit_code == 0
    assert secret not in result.output
    assert "META_ACCESS_TOKEN" not in result.output
