from datetime import UTC, datetime
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from arb import metrics
from arb.models import MetricSnapshot, SaleEvent

PROPERTY = settings(max_examples=150, derandomize=True, deadline=None)
MONEY = st.integers(0, 10**9)
RATE = st.floats(0, 1, allow_nan=False, allow_infinity=False)
NOW = datetime(2026, 10, 5, tzinfo=UTC)


@PROPERTY
@given(value=MONEY)
def test_zero_denominators_are_unknown(value):
    assert metrics.divide(value, 0) is None
    assert metrics.hook_rate(value, 0) is None
    assert metrics.ctr_link(value, 0) is None
    assert metrics.cpc_gross(value, 0) is None
    assert metrics.bridge_rate(value, 0) is None
    assert metrics.epc(value, 0) is None
    assert metrics.roi_expected(value, 0) is None
    assert metrics.waste_ratio(value, 0) is None
    assert metrics.cost_per_learning(value, 0) is None
    assert metrics.max_cpc(None) is None
    assert metrics.hook_rate(value, value, video=False) is None


@PROPERTY
@given(
    spent=MONEY,
    commission=MONEY,
    tax=RATE,
    refund=RATE,
    counts=st.lists(MONEY, min_size=5, max_size=5),
    states=st.lists(st.sampled_from(["approved", "refunded", "chargeback"]), max_size=15),
)
def test_valid_metrics_are_total_and_money_stays_integer(
    spent, commission, tax, refund, counts, states
):
    snapshot = MetricSnapshot(
        entity_id="fixture",
        ts=NOW,
        spend_platform_cents=spent,
        **dict(
            zip(
                ["impressions", "video_3s_views", "link_clicks", "bridge_views", "checkout_clicks"],
                counts,
                strict=True,
            )
        ),
    )
    sales = [
        SaleEvent(
            id=str(i),
            hotmart_tx_id=str(i),
            source="csv",
            ts=NOW,
            commission_cents=commission,
            status=state,
        )
        for i, state in enumerate(states)
    ]
    result = metrics.summarize(snapshot, sales, media_tax_rate=tax, refund_rate=refund)
    assert type(result["spend_gross"]) is int and type(result["rev_expected"]) is int
    assert result["spend_gross"] >= spent and result["rev_expected"] >= 0
    assert result["sales"] == states.count("approved")
    expected = Decimal(commission * states.count("approved")) * (1 - Decimal(str(refund)))
    assert abs(Decimal(result["rev_expected"]) - expected) <= Decimal("0.5")
    assert type(metrics.cash_at_risk(commission, spent)) is int
    assert metrics.spend_gross(spent + 1, tax) >= result["spend_gross"]
