"""Invariantes constitucionais; entradas geradas, sem executor/efeito externo."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from arb.metrics import spend_gross
from arb.models import Entity, MetricSnapshot, SaleEvent
from arb.rules import controls, evaluate, load_rules, scale_allowed

RULES = load_rules()
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
PROPERTY = settings(
    max_examples=100,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@st.composite
def inputs(draw):
    impressions = draw(st.integers(0, 6000))
    clicks = draw(st.integers(0, impressions))
    views = draw(st.integers(0, clicks))
    snapshot = MetricSnapshot(
        entity_id="property",
        ts=NOW,
        impressions=impressions,
        video_3s_views=draw(st.integers(0, impressions)),
        link_clicks=clicks,
        bridge_views=views,
        checkout_clicks=draw(st.integers(0, views)),
        spend_platform_cents=draw(st.integers(0, 40000)),
    )
    count = draw(st.integers(0, 12))
    sales = [
        SaleEvent(
            id=f"sale-{i}",
            hotmart_tx_id=f"tx-{i}",
            source="csv",
            ts=NOW,
            commission_cents=6000,
            status="approved",
            matched_entity_id="property",
        )
        for i in range(count)
    ]
    return snapshot, sales


def entity(gate):
    return Entity(
        id="property",
        kind="ad",
        offer_id="offer",
        geo="CO",
        gate=gate,
        daily_budget_cents=6000,
        status="active",
    )


@pytest.mark.parametrize("gate", ["1", "2", "3", "T"])
@PROPERTY
@given(data=inputs(), extra=st.integers(0, 60000), video=st.booleans())
def test_sample_staleness_and_kill_monotonicity(gate, data, extra, video):
    snapshot, sales = data
    decision = evaluate(entity(gate), snapshot, sales, 6000, RULES, NOW, video=video)
    sampled = (
        snapshot.impressions >= RULES.gate_1.min_impressions
        if gate == "1"
        else snapshot.bridge_views >= RULES.gate_2.min_bridge_views
        if gate == "2"
        else len(sales) >= RULES.gate_3.min_sales
    )
    if not sampled:
        assert decision.verdict != "pass"
        if decision.verdict == "kill":
            assert decision.rule_id.endswith((".cap", ".hard_cap"))
            assert spend_gross(snapshot.spend_platform_cents) >= decision.metrics_json["cap_cents"]
    delayed = snapshot.model_copy(update={"ts": NOW - timedelta(hours=7)})
    assert evaluate(entity(gate), delayed, sales, 6000, RULES, NOW, video=video).verdict != "pass"
    if decision.verdict == "kill":
        larger = snapshot.model_copy(
            update={"spend_platform_cents": snapshot.spend_platform_cents + extra}
        )
        assert (
            evaluate(entity(gate), larger, sales, 6000, RULES, NOW, video=video).verdict == "kill"
        )


@pytest.mark.parametrize("gate", ["3", "T"])
@PROPERTY
@given(data=inputs())
def test_hard_cap_without_confirmation_always_stops(gate, data):
    snapshot, sales = data
    cap = RULES.gate_T.cap_cents if gate == "T" else RULES.gate_3.commission_cap_multiplier * 5100
    snapshot.spend_platform_cents = int(cap * RULES.gate_3.hard_cap_multiplier) + 1
    decision = evaluate(entity(gate), snapshot, sales, 6000, RULES, NOW)
    # A confirmação financeira (ROI e CPC), e não a existência de uma venda, é a exceção.
    if decision.verdict != "pass":
        assert decision.verdict == "kill" and decision.rule_id.endswith(".hard_cap")


@pytest.mark.parametrize("gate", ["1", "2", "3", "T"])
@PROPERTY
@given(spent=st.integers(20000, 60000))
def test_genuine_pass_is_not_overwritten_by_cap(gate, spent):
    snapshot = MetricSnapshot(
        entity_id="property",
        ts=NOW,
        impressions=2000,
        video_3s_views=1000,
        link_clicks=1000,
        bridge_views=1000,
        checkout_clicks=500,
        spend_platform_cents=spent,
    )
    sales = [
        SaleEvent(
            id=str(i),
            hotmart_tx_id=str(i),
            source="csv",
            ts=NOW,
            commission_cents=6000,
            status="approved",
        )
        for i in range(100)
    ]
    assert evaluate(entity(gate), snapshot, sales, 6000, RULES, NOW).verdict == "pass"


@PROPERTY
@given(
    day=st.integers(0, 10**7),
    revenue=st.integers(0, 10**7),
    total=st.integers(0, 10**7),
    passed=st.integers(0, 30),
    validated=st.integers(0, 30),
    current=st.integers(1, 10**7),
    proposed=st.integers(0, 2 * 10**7),
    hours=st.integers(0, 100),
    approved=st.booleans(),
)
def test_controls_never_authorize_spend_and_scale_is_limited(
    day, revenue, total, passed, validated, current, proposed, hours, approved
):
    notices = controls(
        RULES,
        day_spend_cents=day,
        day_revenue_cents=revenue,
        total_spend_cents=total,
        passed_gate_2=passed,
        validated_combos=validated,
    )
    assert all(
        n.split(":")[0] in {"daily_cap", "emergency", "checkpoint", "project_cap"} for n in notices
    )
    allowed = scale_allowed(
        RULES, current, proposed, NOW - timedelta(hours=hours), NOW, approved=approved
    )
    if allowed:
        assert approved and hours >= 24 and current < proposed <= int(current * 1.2)
    if proposed > int(current * 1.2) or hours < 24 or not approved:
        assert not allowed
