from datetime import UTC, datetime

import pytest
from test_plan import launch_fixture

from arb.creative import generate_angles
from arb.models import AngleLearning


def learning(angle, verdict="kill", niche="excel_produtividade"):
    return AngleLearning(
        id="learning",
        angle_id=angle.id,
        offer_id=angle.offer_id,
        niche=niche,
        promise=angle.promise,
        audience_pain=angle.audience_pain,
        hook_line=angle.hook_line,
        formats=["image"],
        geo="CO",
        gate="1",
        verdict=verdict,
        metrics_json={},
        reason="fixture",
        archived_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_three_candidates_deterministic_and_avoid_killed():
    offer, _, _ = launch_fixture()
    first = generate_angles(offer, [])
    assert len(first) == len({a.id for a in first}) == 3
    assert all(a.status == "candidate" and a.offer_id == offer.id for a in first)
    assert first == generate_angles(offer, [])
    killed = learning(first[0], niche=offer.niche)
    assert first[0].id not in {a.id for a in generate_angles(offer, [killed])}
    assert first == generate_angles(offer, [learning(first[0], niche="other")])
    winner = learning(first[2], verdict="pass", niche=offer.niche)
    assert generate_angles(offer, [winner])[0] == first[2]


def test_exhaustion_and_ineligible_fail_closed():
    offer, _, _ = launch_fixture()
    killed = []
    for _ in range(2):
        killed.extend(learning(a, niche=offer.niche) for a in generate_angles(offer, killed))
    with pytest.raises(ValueError, match="revisão humana"):
        generate_angles(offer, killed)
    offer.language = "pt"
    with pytest.raises(ValueError):
        generate_angles(offer, [])
