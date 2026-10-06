from datetime import timedelta

import pytest

from arb.rules import controls, load_rules, scale_allowed


@pytest.mark.parametrize(
    "day,rev,total,g2,combos,prefix",
    [
        (5399, 5399, 5399, 0, 0, None),
        (5400, 5400, 5400, 0, 0, "daily_cap"),
        (3000, 0, 3000, 0, 0, None),
        (3001, 0, 3001, 0, 0, "emergency"),
        (4000, 2000, 4000, 0, 0, None),
        (4000, 1999, 4000, 0, 0, "emergency"),
        (0, 0, 120000, 0, 0, "checkpoint"),
        (0, 0, 120000, 1, 0, None),
        (0, 0, 240000, 1, 0, "project_cap"),
        (0, 0, 240000, 1, 1, "project_cap"),
    ],
)
def test_controls(day, rev, total, g2, combos, prefix):
    result = controls(
        load_rules(),
        day_spend_cents=day,
        day_revenue_cents=rev,
        total_spend_cents=total,
        passed_gate_2=g2,
        validated_combos=combos,
    )
    assert (not result) if prefix is None else any(r.startswith(prefix) for r in result)


def test_scale_requires_approval_interval_and_limit(records):
    ts = records[4].ts
    r = load_rules()
    assert scale_allowed(r, 1000, 1200, ts, ts + timedelta(hours=24), approved=True)
    for proposed, hours, approved in [(1201, 24, True), (1200, 23, True), (1200, 24, False)]:
        assert not scale_allowed(
            r, 1000, proposed, ts, ts + timedelta(hours=hours), approved=approved
        )
