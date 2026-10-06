from pathlib import Path

import pytest

from arb.rules import load_rules
from arb.sim.calibrate import calibrate, html_report, variant


def test_small_grid_deterministic_rules_unchanged(tmp_path):
    path = Path("config/rules.yaml")
    before = path.read_bytes()
    grid = {"gate_3.min_sales": [1, 2], "gate_3.commission_cap_multiplier": [2, 3]}
    first = calibrate(grid=grid, seeds=list(range(5)))
    second = calibrate(grid=grid, seeds=list(range(5)), workers=2)
    assert first == second and len(first["rows"]) == 8
    assert path.read_bytes() == before
    assert any(row["pareto"] for row in first["rows"])
    assert "tbody" in html_report(first, tmp_path / "grid.html").read_text()


@pytest.mark.parametrize(
    "params",
    [
        {"unknown": 1},
        {"gate_3.min_sales": 0},
        {"gate_3.hard_cap_multiplier": 1},
        {"gate_1.kill_ctr_link": 0.012},
    ],
)
def test_invalid_variant(params):
    with pytest.raises(ValueError):
        variant(load_rules(), params)
