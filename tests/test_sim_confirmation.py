"""Planted luck differs from analytic profitability; no market fixture."""

import json
from dataclasses import replace

import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.models import MetricSnapshot, SaleEvent
from arb.rules import load_rules
from arb.sim import population
from arb.sim.calibrate import confirm_report, confirmation_markdown, confirmation_variant
from arb.sim.lab import confirmation_stats, run_lab


def planted(monkeypatch, winner):
    import arb.sim.lab as lab

    p = population(1, offers=1, angles=1, creatives=3)
    for key, truth in p.truth.items():
        # True return <0 for loser; luck is planted independently of this probability.
        p.truth[key] = replace(
            truth,
            ctr=0.02,
            checkout=0.3,
            purchase=0.5 if winner else 0.001,
            winner=winner,
            cpm_cents=1000,
        )
    monkeypatch.setattr(lab, "population", lambda *a, **k: p)
    calls = {}

    def traffic(e, t, rng, ts):
        calls[e.id] = calls.get(e.id, 0) + 1
        n = int(winner or (calls[e.id] == 1 and not e.id.endswith("c2")))
        snap = MetricSnapshot(
            entity_id=e.id,
            ts=ts,
            impressions=1000,
            video_3s_views=400,
            link_clicks=20,
            spend_platform_cents=1000,
            bridge_views=20,
            checkout_clicks=6,
        )
        sales = (
            [
                SaleEvent(
                    id=e.id + str(calls[e.id]),
                    hotmart_tx_id=e.id + str(calls[e.id]),
                    source="csv",
                    ts=ts,
                    commission_cents=6000,
                    status="approved",
                    matched_entity_id=e.id,
                )
            ]
            if n
            else []
        )
        return snap, sales

    monkeypatch.setattr(lab, "traffic", traffic)


@pytest.mark.parametrize("winner", [False, True])
def test_planted_luck_and_winner_counted_against_truth(monkeypatch, winner):
    planted(monkeypatch, winner)
    off = confirmation_stats(run_lab(1))
    # Each invocation receives fresh synthetic population/state.
    planted(monkeypatch, winner)
    on = confirmation_stats(run_lab(1, rules=confirmation_variant(load_rules(), "C-15000")))
    if winner:
        assert off["true_validations"] == on["true_validations"] == 1
        assert off["false_validations"] == on["false_validations"] == 0
    else:
        assert off["false_validations"] == 1 and on["false_validations"] == 0
        assert on["true_losers"] == 1


def test_determinism_arithmetic_and_markdown(tmp_path):
    first = confirm_report(seeds=[0, 7, 42])
    second = confirm_report(seeds=[0, 7, 42], workers=2)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert len(first["rows"]) == 12
    assert first["hypotheses_not_market_data"]
    for row in first["rows"]:
        assert row["true_validations"] + row["missed_winners"] == row["true_winners"]
        if row["true_losers"]:
            assert row["false_positive_rate"] == row["false_validations"] / row["true_losers"]
        if row["true_validations"]:
            assert (
                row["spend_per_true_winner_cents"]
                == row["spend_gross_cents"] / row["true_validations"]
            )
    assert "hipóteses" in confirmation_markdown(first)
    output = tmp_path / "report.json"
    args = [
        "sim",
        "confirm-report",
        "--seeds",
        "0-0",
        "--output",
        str(output),
        "--report",
        str(tmp_path / "report.md"),
    ]
    assert CliRunner().invoke(app, args).exit_code == 0
    assert len(json.loads(output.read_text())["rows"]) == 12


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seeds": []},
        {"seeds": [1, 1]},
        {"seeds": [True]},
        {"profiles": ["unknown"]},
        {"variants": []},
        {"variants": ["current", "current"]},
        {"variants": ["C-9999"]},
        {"workers": 0},
        {"workers": 9},
    ],
)
def test_invalid_inputs_fail_closed(kwargs):
    with pytest.raises(ValueError):
        confirm_report(**kwargs)


@pytest.mark.parametrize("seeds", ["-1-2", "10-1", "foo", "0-10000"])
def test_cli_rejects_invalid_range(seeds):
    assert CliRunner().invoke(app, ["sim", "confirm-report", "--seeds", seeds]).exit_code != 0


@pytest.mark.parametrize("case", ["config", "same", "symlink"])
def test_report_paths_do_not_overwrite_configuration(tmp_path, monkeypatch, case):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "config/rules.yaml"
    target.parent.mkdir()
    target.write_text("synthetic sentinel")
    output = target if case == "config" else tmp_path / "report.json"
    report = output if case == "same" else tmp_path / "report.md"
    if case == "symlink":
        output.symlink_to(target)
    result = CliRunner().invoke(
        app,
        [
            "sim",
            "confirm-report",
            "--seeds",
            "0-0",
            "--output",
            str(output),
            "--report",
            str(report),
        ],
    )
    assert result.exit_code != 0
    assert target.read_text() == "synthetic sentinel"
    assert not report.exists()
