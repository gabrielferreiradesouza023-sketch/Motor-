import pytest

from arb import metrics as m


@pytest.mark.parametrize(
    "fn,args,expected",
    [
        (m.spend_gross, (1000,), 1130),
        (m.spend_gross, (50,), 57),
        (m.hook_rate, (300, 1000), 0.3),
        (m.ctr_link, (12, 1000), 0.012),
        (m.cpc_gross, (1130, 10), 113),
        (m.bridge_rate, (6, 40), 0.15),
        (m.epc, (5100, 50), 102),
        (m.max_cpc, (100,), 70),
        (m.roi_expected, (1300, 1000), 0.3),
        (m.waste_ratio, (100, 2000), 0.05),
        (m.cost_per_learning, (2000, 4), 500),
        (m.cash_at_risk, (1000, 300), 700),
    ],
)
def test_known_values(fn, args, expected):
    assert fn(*args) == pytest.approx(expected)


@pytest.mark.parametrize(
    "fn",
    [
        m.hook_rate,
        m.ctr_link,
        m.cpc_gross,
        m.bridge_rate,
        m.epc,
        m.roi_expected,
        m.waste_ratio,
        m.cost_per_learning,
    ],
)
def test_zero_denominator(fn):
    assert fn(10, 0) is None


def test_revenue_refund_and_image(records):
    sale = records[5]
    refunded = sale.model_copy(update={"id": "ref", "status": "refunded"})
    assert m.rev_expected([sale, refunded]) == 4250
    assert m.rev_expected([]) == 0
    assert m.hook_rate(0, 1000, video=False) is None
    assert m.max_cpc(None) is None
    assert m.summarize(records[4], [sale])["spend_gross"] == 1130
