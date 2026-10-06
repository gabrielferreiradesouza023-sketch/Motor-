import fcntl
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from arb import preflight
from arb.cli import app
from arb.db import backup_daily, connect, migrate
from arb.meta.read import Reader

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configured(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    database = tmp_path / "data/engine.db"
    conn = connect(database)
    migrate(conn)
    backup_daily(conn, database.parent / "backups", day=NOW.date())
    conn.close()
    lock = database.with_suffix(".db.scheduler.lock")
    lock.write_text("preserve scheduler file")
    for name in (
        *preflight.REQUIRED_CREDENTIALS,
        "APPROVAL_SIGNING_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.setenv(name, "synthetic-private-value-" + name.lower())
    monkeypatch.setenv("META_API_VERSION", "v99.0")
    monkeypatch.setenv("CARD_LIMIT_CENTS", "240000")
    return tmp_path, database, lock


def reader_with(body=None, status=200):
    body = (
        {"currency": "BRL", "timezone_name": "America/Sao_Paulo", "spend_cap": "240000"}
        if body is None
        else body
    )
    seen = []

    def handler(request):
        assert request.method == "GET"
        seen.append(request)
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
    return (
        Reader("synthetic-read-token", "act_123", "v99.0", client=client, attempts=1),
        client,
        seen,
    )


def by_name(result):
    return {c["name"]: c for c in result["checks"]}


def run_check(configured, *, body=None, status=200):
    root, database, _ = configured
    reader, client, seen = reader_with(body, status)
    try:
        return preflight.inspect(root=root, database=database, reader=reader, now=NOW), seen
    finally:
        client.close()


def test_all_green_readonly_and_no_sensitive_values(configured):
    root, database, lock = configured
    before = {p: p.read_bytes() for p in [database, lock, root / "config/rules.yaml"]}
    result, seen = run_check(configured)
    assert result["ok"] and all(c["status"] == "ok" for c in result["checks"])
    assert len(seen) == 2
    assert {p: p.read_bytes() for p in before} == before
    assert "synthetic-private-value" not in json.dumps(result)
    assert "synthetic-read-token" not in json.dumps(result)


@pytest.mark.parametrize(
    "name,check",
    [(n, "credentials") for n in preflight.REQUIRED_CREDENTIALS]
    + [
        ("APPROVAL_SIGNING_KEY", "approval_signing_key"),
        ("META_API_VERSION", "graph_version"),
        ("CARD_LIMIT_CENTS", "card_limit"),
    ],
)
def test_missing_names_are_errors(configured, monkeypatch, name, check):
    monkeypatch.delenv(name)
    result, _ = run_check(configured)
    assert not result["ok"] and by_name(result)[check]["status"] == "erro"


@pytest.mark.parametrize(
    "limit", ["", "0", "-1", "240001", "6000.0", "synthetic-sensitive-marker", "9" * 5000]
)
def test_card_limit_errors_never_echo_value(configured, monkeypatch, limit):
    monkeypatch.setenv("CARD_LIMIT_CENTS", limit)
    result, _ = run_check(configured)
    assert by_name(result)["card_limit"]["status"] == "erro"
    assert "synthetic-sensitive-marker" not in json.dumps(result)


@pytest.mark.parametrize(
    "cap", ["0", "240001", None, True, "1.0", "synthetic-sensitive-marker", "9" * 5000]
)
def test_meta_cap_missing_disabled_invalid_or_too_large(configured, cap):
    result, seen = run_check(
        configured, body={"currency": "BRL", "timezone_name": "America/Sao_Paulo", "spend_cap": cap}
    )
    assert by_name(result)["meta_spend_cap"]["status"] == "erro" and len(seen) == 2
    assert "synthetic-sensitive-marker" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,body",
    [
        (400, {"error": {"code": 190, "message": "synthetic-sensitive-marker"}}),
        (200, {"currency": "USD", "timezone_name": "America/Sao_Paulo"}),
        (503, {"error": {"message": "synthetic-sensitive-marker"}}),
    ],
)
def test_meta_failures_sanitized(configured, status, body):
    result, _ = run_check(configured, body=body, status=status)
    assert by_name(result)["meta_spend_cap"]["status"] == "erro"
    assert "synthetic-sensitive-marker" not in json.dumps(result)


@pytest.mark.parametrize("change", ["missing", "corrupt", "database_missing"])
def test_backup_errors(configured, change):
    root, database, _ = configured
    backup = database.parent / "backups" / "engine-2026-10-06.db"
    if change == "missing":
        backup.unlink()
    elif change == "corrupt":
        backup.write_text("corrupt")
    else:
        database.unlink()
    result, _ = run_check(configured)
    assert by_name(result)["backup_restore"]["status"] == "erro"


@pytest.mark.parametrize("change", ["missing", "occupied"])
def test_scheduler_lock_errors(configured, change):
    _, _, lock = configured
    if change == "missing":
        lock.unlink()
        result, _ = run_check(configured)
    else:
        with lock.open("rb") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, _ = run_check(configured)
    assert by_name(result)["scheduler_lock"]["status"] == "erro"


def test_alert_optional_and_writer_missing(configured, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    result, _ = run_check(configured)
    assert result["ok"] and by_name(result)["alerts"]["status"] == "aviso"
    monkeypatch.setattr(preflight, "PauseWriter", None)
    result, _ = run_check(configured)
    assert not result["ok"] and by_name(result)["panic_writer"]["status"] == "erro"


def test_rules_version_and_default_no_network(configured, monkeypatch):
    root, database, _ = configured

    def forbidden(*args, **kwargs):
        raise AssertionError("cliente real proibido")

    monkeypatch.setattr(httpx, "Client", forbidden)
    result = preflight.inspect(root=root, database=database, now=NOW)
    assert by_name(result)["meta_spend_cap"]["status"] == "erro"
    monkeypatch.setenv("META_API_VERSION", "synthetic-sensitive-marker")
    (root / "config/rules.yaml").write_text("invalid")  # só cópia temporária do teste
    result = preflight.inspect(root=root, database=database, now=NOW)
    assert by_name(result)["rules"]["status"] == "erro"
    assert by_name(result)["graph_version"]["status"] == "erro"
    assert "synthetic-sensitive-marker" not in json.dumps(result)


def test_cli_json_human_exit_and_opt_in_only_mock(configured, monkeypatch):
    root, database, _ = configured
    cli = CliRunner()
    command = ["preflight", "--root", str(root), "--database", str(database)]
    result = cli.invoke(app, command + ["--json"])
    assert result.exit_code == 1 and not json.loads(result.output)["ok"]
    assert "synthetic-private-value" not in result.output
    result = cli.invoke(app, command)
    assert result.exit_code == 1 and "Correção:" in result.output
    reader, client, seen = reader_with()
    monkeypatch.setattr(preflight, "make_reader", lambda _: reader)
    # CLI usa dia atual UTC, preparando somente backup sintético desse dia.
    conn = connect(database)
    backup_daily(conn, database.parent / "backups")
    conn.close()
    try:
        result = cli.invoke(app, command + ["--json", "--read-meta"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["ok"] and len(seen) == 2
    finally:
        client.close()


def test_signing_key_is_never_read_even_when_present(configured, monkeypatch):
    from types import SimpleNamespace

    original = preflight.os.environ

    class NamesOnlyKey(dict):
        def __getitem__(self, name):
            if name == "APPROVAL_SIGNING_KEY":
                raise AssertionError("valor HMAC jamais deve ser lido")
            return super().__getitem__(name)

        def get(self, name, default=None):
            if name == "APPROVAL_SIGNING_KEY":
                raise AssertionError("valor HMAC jamais deve ser lido")
            return super().get(name, default)

    monkeypatch.setattr(preflight, "os", SimpleNamespace(environ=NamesOnlyKey(original)))
    result, _ = run_check(configured)
    assert result["ok"]


def test_graph_requires_environment_even_when_settings_exist(configured, monkeypatch):
    root, _, _ = configured
    monkeypatch.delenv("META_API_VERSION")
    settings = root / "config/settings.yaml"
    for value in ["meta_api_version: 123", "bad", "meta_api_version: null"]:
        settings.write_text(value)
        result, _ = run_check(configured)
        assert by_name(result)["graph_version"]["status"] == "erro"
