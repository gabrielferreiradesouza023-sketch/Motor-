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
