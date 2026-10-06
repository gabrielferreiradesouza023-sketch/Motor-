import json
from pathlib import Path

import pytest
from conftest import pinned_rules
from pydantic import ValidationError

from arb.config import SimProfiles, load_sim_profiles
from arb.sim import population
from arb.sim.lab import run_lab


def test_profiles_strict_and_positions():
    profiles = load_sim_profiles()
    invalid = profiles.model_dump()
    invalid["realistic"]["winner"]["cpm_cents"] = [2000, 800]
    with pytest.raises(ValidationError):
        SimProfiles.model_validate(invalid)
    invalid = profiles.model_dump()
    invalid["realistic"]["winner"]["surprise"] = 1
    with pytest.raises(ValidationError):
        SimProfiles.model_validate(invalid)
    positions = []
    for seed in range(10):
        p = population(seed, profile="realistic")
        assert p.truth == population(seed, profile="realistic").truth
        assert any(t.role == "borderline_winner" for t in p.truth.values())
        positions.append(next(c.angle_id for c in p.creatives if p.truth[c.id].winner))
    assert len(set(positions)) > 1
    with pytest.raises(ValueError):
        population(42, profile="unknown")


def test_planted_matches_versioned_history():
    previous = json.loads(Path("docs/validation/f1-50-seeds.json").read_text())
    # Histórico gravado com G3 anterior ao ADR-018; regressão do algoritmo, não das regras.
    runs = [run_lab(seed, rules=pinned_rules()).summary() for seed in range(50)]
    assert [
        {key: run[key] for key in old} for run, old in zip(runs, previous["runs"], strict=True)
    ] == previous["runs"]
    assert all(r["planted_found"] for r in runs)
    assert sum(r["waste_ratio"] for r in runs) / 50 == pytest.approx(previous["mean_waste_ratio"])


@pytest.mark.parametrize("profile", ["realistic", "pessimistic"])
def test_two_hundred_seeds_without_exception(profile):
    runs = [run_lab(seed, profile=profile).summary() for seed in range(200)]
    assert all(r["spend_gross_cents"] <= 240000 for r in runs)
    assert run_lab(42, profile=profile).summary() == run_lab(42, profile=profile).summary()
