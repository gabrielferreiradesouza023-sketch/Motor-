import pytest

from arb.launcher import plan, plan_hash, validate_plan
from arb.sim import population


def launch_fixture():
    pop = population(42)
    offer = pop.offers[0].model_copy(update={"status": "approved"})
    angles = [
        a.model_copy(update={"status": "approved"}) for a in pop.angles if a.offer_id == offer.id
    ]
    creatives = [
        c.model_copy(update={"status": "approved", "policy_lint": "passed"})
        for c in pop.creatives
        if c.angle_id in {a.id for a in angles}
    ]
    return offer, angles, creatives


def test_plan_structure_hash_and_limits():
    offer, angles, creatives = launch_fixture()
    value = plan(
        offer,
        angles,
        creatives,
        geo="CO",
        daily_budget_cents=6000,
        destination_url="https://bridge.example.test/oferta",
    )
    assert len(value.entities) == 13
    assert all(e.status == "paused" and e.meta_id is None for e in value.entities)
    assert sum(e.daily_budget_cents for e in value.entities) == 6000
    assert plan_hash(value) == plan_hash(
        plan(
            offer,
            angles[::-1],
            creatives[::-1],
            geo="CO",
            daily_budget_cents=6000,
            destination_url=str(value.destination_url),
        )
    )
    assert validate_plan(value) == value
    value.entities[0].status = "active"
    with pytest.raises(ValueError, match="divergente"):
        validate_plan(value)


@pytest.mark.parametrize(
    "change", ["offer", "angle", "lint", "missing", "duplicate", "budget", "geo"]
)
def test_plan_rejects_ineligible(change):
    offer, angles, creatives = launch_fixture()
    budget, geo = 6000, "CO"
    if change == "offer":
        offer.status = "candidate"
    if change == "angle":
        angles[0].status = "candidate"
    if change == "lint":
        creatives[0].policy_lint = "failed"
    if change == "missing":
        creatives.pop()
    if change == "duplicate":
        creatives.append(creatives[0])
    if change == "budget":
        budget = 6001
    if change == "geo":
        geo = "MX"
    with pytest.raises(ValueError):
        plan(
            offer,
            angles,
            creatives,
            geo=geo,
            daily_budget_cents=budget,
            destination_url="https://bridge.example.test/oferta",
        )
