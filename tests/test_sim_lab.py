from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect
from arb.models import MetricSnapshot
from arb.sim.lab import persist, run_lab


def test_fifty_seeds_acceptance():
    runs = [run_lab(seed).summary() for seed in range(50)]
    found = sum(r["planted_found"] for r in runs) / len(runs)
    waste = sum(r["waste_ratio"] or 0 for r in runs) / len(runs)
    assert found >= 0.8, runs
    assert waste < 0.1
    assert all(r["spend_gross_cents"] <= 240000 for r in runs)


def test_seed_repeat_persistence_and_budget(tmp_path):
    run = run_lab(42)
    assert run.summary() == run_lab(42).summary()
    assert run_lab(42, 5000).summary()["spend_gross_cents"] <= 5000
    path = tmp_path / "simulation.db"
    persist(run, path)
    connection = connect(path)
    assert Repository(connection, MetricSnapshot).list()
    connection.close()
    with pytest.raises(ValueError, match="já existe"):
        persist(run, path)


def test_cli_smoke():
    result = CliRunner().invoke(app, ["sim", "run", "--seed", "42", "--budget", "2400"])
    assert result.exit_code == 0, result.output
    assert '"planted_found": true' in result.output
    assert not Path("data/simulation.db").exists()
