import json
from pathlib import Path

import pytest

from arb.db import Repository, connect, migrate
from arb.models import Approval
from arb.scout import import_adlibrary, import_offers
from arb.scout.ranking import propose, rank

ROOT = Path(__file__).resolve().parents[1]


def test_known_ranking_filters_and_pending_approval(tmp_path):
    offers = import_offers(ROOT / "examples/scout/offers.csv")
    ads = import_adlibrary(ROOT / "examples/scout/adlibrary.csv")
    ranked, rejected = rank(offers, ads)
    assert [o.id for o in ranked] == ["excel", "pets", "croche"]
    assert "blocked" in rejected
    connection = connect(tmp_path / "scout.db")
    migrate(connection)
    path = propose(connection, ranked, tmp_path / "pending")
    document = json.loads(path.read_text())
    assert len(document["plan"]["offers"]) == 3
    assert document["approval"]["status"] == "pending"
    assert document["approval"]["max_exposure_cents"] == 0
    assert propose(connection, ranked, tmp_path / "pending") == path
    assert len(Repository(connection, Approval).list()) == 1
    assert all(o.status == "candidate" for o in ranked)
    connection.close()


@pytest.mark.parametrize(
    "change", [{"allows_paid_traffic": False}, {"commission_brl_cents": 3999}, {"language": "pt"}]
)
def test_eliminatory_filters(change):
    item = import_offers(ROOT / "examples/scout/offers.csv")[0]
    modified = item.model_copy(update={"offer": item.offer.model_copy(update=change)})
    ranked, rejected = rank([modified], [])
    assert ranked == [] and item.offer.id in rejected


def test_documented_cli_options(tmp_path):
    from typer.testing import CliRunner

    from arb.cli import app

    runner = CliRunner()
    arguments = [
        "--offers",
        str(ROOT / "examples/scout/offers.csv"),
        "--adlibrary",
        str(ROOT / "examples/scout/adlibrary.csv"),
        "--database",
        str(tmp_path / "scout.db"),
    ]
    imported = runner.invoke(app, ["scout", "import", *arguments])
    assert imported.exit_code == 0, imported.output
    ranked = runner.invoke(
        app, ["scout", "rank", *arguments, "--output", str(tmp_path / "pending")]
    )
    assert ranked.exit_code == 0, ranked.output
    assert '"excel"' in ranked.output and '"blocked"' in ranked.output
