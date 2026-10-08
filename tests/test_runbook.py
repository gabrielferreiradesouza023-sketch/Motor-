from pathlib import Path

from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.models import Action, Entity, Offer
from arb.scout import import_offers

ROOT = Path(__file__).resolve().parents[1]


def test_runbook_backup_panic_restore_and_repeat(tmp_path, records):
    database = tmp_path / "runbook.db"
    conn = connect(database)
    migrate(conn)
    with conn:
        Repository(conn, Offer).add(records[0])
        Repository(conn, Entity).add(
            records[3].model_copy(
                update={"creative_id": None, "angle_id": None, "status": "active"}
            )
        )
    conn.close()
    cli = CliRunner()
    backup = cli.invoke(
        app, ["db", "backup", "--database", str(database), "--output", str(tmp_path / "backups")]
    )
    assert backup.exit_code == 0, backup.output
    assert cli.invoke(app, ["panic", "--database", str(database)]).exit_code == 0
    conn = connect(database)
    assert Repository(conn, Entity).get("entity").status == "paused"
    assert len(Repository(conn, Action).list()) == 1
    conn.close()
    assert cli.invoke(app, ["panic", "--database", str(database)]).exit_code == 0
    snapshot = next((tmp_path / "backups").glob("*.db"))
    restored = tmp_path / "recovered.db"
    result = cli.invoke(app, ["db", "restore", str(snapshot), "--database", str(restored)])
    assert result.exit_code == 0, result.output
    conn = connect(restored)
    assert Repository(conn, Entity).get("entity").status == "active"  # snapshot anterior ao panic
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()
    # Restauração preserva estado antigo; runbook exige panic antes de usar a cópia.
    assert cli.invoke(app, ["panic", "--database", str(restored)]).exit_code == 0
    refused = cli.invoke(app, ["db", "restore", str(snapshot), "--database", str(database)])
    assert refused.exit_code != 0 and "destino existe" in refused.output


def test_corrupt_restore_and_remote_panic_are_explicit(tmp_path, records):
    cli = CliRunner()
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not sqlite")
    restored = tmp_path / "new.db"
    assert (
        cli.invoke(app, ["db", "restore", str(corrupt), "--database", str(restored)]).exit_code != 0
    )
    assert not restored.exists()
    database = tmp_path / "remote.db"
    conn = connect(database)
    migrate(conn)
    with conn:
        Repository(conn, Offer).add(records[0])
        Repository(conn, Entity).add(
            records[3].model_copy(
                update={
                    "meta_id": "observed-real",
                    "status": "active",
                    "creative_id": None,
                    "angle_id": None,
                }
            )
        )
    conn.close()
    result = cli.invoke(app, ["panic", "--database", str(database)])
    assert result.exit_code == 1 and "remote_pause_pending" in result.output
    conn = connect(database)
    assert Repository(conn, Entity).get("entity").status == "active"
    conn.close()


def test_creative_cli_candidates_without_accounts(tmp_path):
    cli = CliRunner()
    database = tmp_path / "creative.db"
    conn = connect(database)
    migrate(conn)
    offer = import_offers(ROOT / "examples/scout/offers.csv")[0].offer
    with conn:
        Repository(conn, Offer).add(offer)
    conn.close()
    result = cli.invoke(app, ["creative", "angles", offer.id, "--database", str(database)])
    assert result.exit_code == 0, result.output
    import json

    angle = json.loads(result.output.splitlines()[0])
    result = cli.invoke(
        app, ["creative", "copies", angle["id"], "--region", "CO", "--database", str(database)]
    )
    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) == 3


def test_token_rotation_recreates_readonly_client_without_logging_secrets():
    import httpx

    from arb.meta.read import Reader

    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for token in ("synthetic-token-before", "synthetic-token-after"):
            reader = Reader(token, "act_123", "v99.0", client=client)
            assert reader.account()["currency"] == "BRL"
    assert seen[0] != seen[1]
    assert len(seen) == 2


def test_incident_runbook_commands_really_exist():
    import re
    import shlex

    text = (ROOT / "docs/runbooks/incidentes.md").read_text()
    commands = set()
    for line in re.findall(r"^uv run arb (.+)$", text, flags=re.MULTILINE):
        words = shlex.split(line)
        length = 2 if words[0] in {"db", "ops", "scheduler", "drill"} else 1
        commands.add(tuple(words[:length]))
    assert commands == {
        ("ops", "pending"),
        ("ops", "reconcile"),
        ("preflight",),
        ("scheduler", "once"),
        ("db", "drill"),
        ("db", "restore"),
        ("doctor",),
        ("panic",),
        ("db", "release"),
        ("db", "backup"),
        ("drill", "run"),
    }
    for command in commands:
        result = CliRunner().invoke(app, [*command, "--help"])
        assert result.exit_code == 0, (command, result.output)
    assert not any(c[0] in {"launch", "activate", "scale"} for c in commands)


def test_incident_scenarios_match_exercised_drill_reference():
    import json
    import re

    from arb.drill import run

    text = (ROOT / "docs/runbooks/incidentes.md").read_text()
    names = set(re.findall(r"<!-- drill: ([a-z_0-9]+) -->", text))
    reference = json.loads((ROOT / "docs/validation/drill-seed-42.json").read_text())["scenarios"]
    assert names == set(reference) and len(names) == 7
    assert run(42)["scenarios"] == reference
    assert all(reference.values())


def test_operator_commands_exist_and_do_not_increase_exposure():
    import re
    import shlex

    text = (ROOT / "docs/runbooks/operador.md").read_text()
    commands = set()
    groups = {"db", "scheduler", "service", "validate", "evidence", "accept", "approve"}
    for line in re.findall(r"^uv run arb (.+)$", text, flags=re.MULTILINE):
        words = shlex.split(line)
        commands.add(tuple(words[: 2 if words[0] in groups else 1]))
    assert commands == {
        ("doctor",),
        ("service", "status"),
        ("db", "migrate"),
        ("scheduler", "once"),
        ("db", "backup"),
        ("db", "drill"),
        ("service", "render"),
        ("service", "check"),
        ("service", "install-plan"),
        ("validate", "record"),
        ("validate", "show"),
        ("preflight",),
        ("accept", "f5"),
        ("accept", "register-test"),
        ("accept", "pause"),
        ("evidence", "sign"),
        ("evidence", "verify"),
        ("accept", "tracking-propose"),
        ("approve", "sign"),
        ("approve", "verify"),
        ("accept", "tracking"),
        ("readiness",),
    }
    for command in commands:
        result = CliRunner().invoke(app, [*command, "--help"])
        assert result.exit_code == 0, (command, result.output)
    assert not any(c[0] in {"launch", "activate", "scale", "deploy"} for c in commands)
    assert "tracking_test" in text and "exposição zero" in text


def test_operator_document_has_no_secret_values_or_operational_live_assignment():
    import re

    text = (ROOT / "docs/runbooks/operador.md").read_text()
    assert not re.search(r"\bLIVE_MODE\s*=\s*true\b", text)
    assert not re.search(r"\b(?:[a-fA-F0-9]{64}|[a-fA-F0-9]{128})\b", text)
    assert not re.search(r"(?:TOKEN|SECRET|SIGNING_KEY)\s*=\s*\S+", text)
    assert not re.search(r"(?:cat|type|Get-Content)\s+[^\n]*(?:\.env|approval_ed25519)", text)
    for item in [f"V-{n:02d}" for n in range(1, 7)]:
        assert item in text
    assert "export PYTHONUTF8=1" in text and '$env:PYTHONUTF8 = "1"' in text
    assert text.count("Enviar ao Claude") >= 7
    assert "evidência não assinada" in text and "sete dias" in text and "48 horas" in text


def test_operator_internal_links_resolve():
    import re

    document = ROOT / "docs/runbooks/operador.md"
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text())
    internal = [link for link in links if not link.startswith("https://")]
    assert len(internal) >= 6
    for link in internal:
        parts = link.split("#", 1)
        target = (document.parent / parts[0]).resolve()
        assert target.is_file(), link
        if len(parts) == 2:
            headings = re.findall(r"^#+ (.+)$", target.read_text(), flags=re.MULTILINE)
            anchors = {
                re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-") for title in headings
            }
            assert parts[1] in anchors, link
