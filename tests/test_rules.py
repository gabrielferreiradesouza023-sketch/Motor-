from datetime import timedelta

import pytest

from arb.rules import evaluate, load_rules


@pytest.mark.parametrize(
    "gate,changes,verdict",
    [
        ("1", {"impressions": 999}, "insufficient_data"),
        ("1", {"impressions": 1000, "link_clicks": 12}, "pass"),
        ("1", {"impressions": 1000, "link_clicks": 7}, "kill"),
        ("1", {"impressions": 1000, "link_clicks": 10}, "hold"),
        ("1", {"impressions": 0, "spend_platform_cents": 1328}, "kill"),
        ("2", {"bridge_views": 39, "checkout_clicks": 10}, "insufficient_data"),
        ("2", {"bridge_views": 40, "checkout_clicks": 6}, "pass"),
        ("2", {"bridge_views": 40, "checkout_clicks": 3}, "kill"),
        ("2", {"bridge_views": 40, "checkout_clicks": 4}, "hold"),
        ("3", {"spend_platform_cents": 8000}, "kill"),
        ("T", {"spend_platform_cents": 7100}, "kill"),
    ],
)
def test_gate_boundaries(records, gate, changes, verdict):
    entity = records[3].model_copy(update={"gate": gate})
    snapshot = records[4].model_copy(update=changes)
    result = evaluate(entity, snapshot, [], 5000, load_rules(), snapshot.ts, video=False)
    assert result.verdict == verdict
    assert result.reason and result.rule_id


def test_video_and_stale(records):
    entity, snapshot = records[3:5]
    assert evaluate(entity, snapshot, [], 5000, load_rules(), snapshot.ts).verdict == "kill"
    for hours, expected in [(6, "pass"), (7, "insufficient_data")]:
        decision = evaluate(
            entity,
            snapshot,
            [],
            5000,
            load_rules(),
            snapshot.ts + timedelta(hours=hours),
            video=False,
        )
        assert decision.verdict == expected
    expensive = snapshot.model_copy(update={"spend_platform_cents": 2000})
    assert (
        evaluate(
            entity, expensive, [], 5000, load_rules(), snapshot.ts + timedelta(hours=7), video=False
        ).verdict
        == "kill"
    )


def test_money_gate_and_transfer(records):
    sales = [
        records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)}) for n in range(3)
    ]
    entity = records[3].model_copy(update={"gate": "3"})
    snapshot = records[4]
    assert evaluate(entity, snapshot, sales, 5000, load_rules(), snapshot.ts).verdict == "pass"
    assert (
        evaluate(entity, snapshot, sales[:2], 5000, load_rules(), snapshot.ts).verdict
        == "insufficient_data"
    )
    # Vendas existem mas não validam ROI; G3 não permite kill automático por teto nesse caso.
    snapshot = snapshot.model_copy(update={"spend_platform_cents": 20000})
    assert evaluate(entity, snapshot, sales, 5000, load_rules(), snapshot.ts).verdict == "hold"
