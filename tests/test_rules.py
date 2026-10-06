from datetime import timedelta

import pytest
from conftest import pinned_rules

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
    result = evaluate(entity, snapshot, [], 5000, pinned_rules(), snapshot.ts, video=False)
    assert result.verdict == verdict
    assert result.reason and result.rule_id


def test_video_and_stale(records):
    entity, snapshot = records[3:5]
    assert evaluate(entity, snapshot, [], 5000, pinned_rules(), snapshot.ts).verdict == "kill"
    for hours, expected in [(6, "pass"), (7, "insufficient_data")]:
        decision = evaluate(
            entity,
            snapshot,
            [],
            5000,
            pinned_rules(),
            snapshot.ts + timedelta(hours=hours),
            video=False,
        )
        assert decision.verdict == expected
    expensive = snapshot.model_copy(update={"spend_platform_cents": 2000})
    assert (
        evaluate(
            entity,
            expensive,
            [],
            5000,
            pinned_rules(),
            snapshot.ts + timedelta(hours=7),
            video=False,
        ).verdict
        == "kill"
    )


def test_money_gate_and_transfer(records):
    sales = [
        records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)}) for n in range(3)
    ]
    entity = records[3].model_copy(update={"gate": "3"})
    snapshot = records[4]
    assert evaluate(entity, snapshot, sales, 5000, pinned_rules(), snapshot.ts).verdict == "pass"
    assert (
        evaluate(entity, snapshot, sales[:2], 5000, pinned_rules(), snapshot.ts).verdict
        == "insufficient_data"
    )
    # Vendas existem mas não validam ROI: entre teto e teto rígido, continua em hold.
    # Teto = 2 × int(5000 × 0,85) = 8500; teto rígido = 12750 brutos (ADR-016).
    snapshot = snapshot.model_copy(update={"spend_platform_cents": 10000})
    assert evaluate(entity, snapshot, sales, 5000, pinned_rules(), snapshot.ts).verdict == "hold"


@pytest.mark.parametrize("gate", ["3", "T"])
@pytest.mark.parametrize(
    "platform_cents,sale_count,verdict,rule",
    [
        # 11283 × 1,13 = 12750 brutos: exatamente no teto rígido do G3.
        (11283, 1, "kill", "hard_cap"),
        (11283, 2, "kill", "hard_cap"),
        (11282, 2, "insufficient_data", "sample"),
        # Com 3 vendas, ROI ruim e acima do teto rígido também morre.
        (20000, 3, "kill", "hard_cap"),
    ],
)
def test_hard_cap_kills_unvalidated_money_gate(
    records, gate, platform_cents, sale_count, verdict, rule
):
    rules = pinned_rules()
    sales = [
        records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)})
        for n in range(sale_count)
    ]
    entity = records[3].model_copy(update={"gate": gate})
    if gate == "T":
        # Teto T = 8000 brutos; teto rígido 12000. Escala os gastos para o mesmo limite.
        platform_cents = {11283: 10620, 11282: 10619, 20000: 20000}[platform_cents]
    snapshot = records[4].model_copy(update={"spend_platform_cents": platform_cents})
    decision = evaluate(entity, snapshot, sales, 5000, rules, snapshot.ts)
    assert decision.verdict == verdict
    assert decision.rule_id == f"g{gate}.{rule}"
    expected_cap = 8000 if gate == "T" else 8500
    assert decision.metrics_json["hard_cap_cents"] == int(expected_cap * 1.5)


def test_hard_cap_never_overrides_validated_combo(records):
    sales = [
        records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)}) for n in range(3)
    ]
    entity = records[3].model_copy(update={"gate": "3"})
    decision = evaluate(entity, records[4], sales, 5000, pinned_rules(), records[4].ts)
    assert decision.verdict == "pass"
    assert decision.metrics_json["hard_cap_cents"] == 12750


def test_hard_cap_multiplier_must_exceed_one():
    rules = pinned_rules().model_dump()
    rules["gate_3"]["hard_cap_multiplier"] = 1.0
    with pytest.raises(ValueError):
        type(load_rules()).model_validate(rules)


def test_adr018_calibration_in_rules_yaml(records):
    """ADR-018 (aceito): G3 com 2 vendas e teto nominal 3× comissão líquida."""
    rules = load_rules()
    assert rules.gate_3.min_sales == 2
    assert rules.gate_3.commission_cap_multiplier == 3
    sales = [
        records[5].model_copy(update={"id": str(n), "hotmart_tx_id": str(n)}) for n in range(2)
    ]
    entity = records[3].model_copy(update={"gate": "3"})
    decision = evaluate(entity, records[4], sales, 5000, rules, records[4].ts)
    assert decision.verdict == "pass"
    assert decision.metrics_json["cap_cents"] == 3 * 4250
    assert decision.metrics_json["hard_cap_cents"] == int(3 * 4250 * 1.5)
    one_sale = evaluate(entity, records[4], sales[:1], 5000, rules, records[4].ts)
    assert one_sale.verdict == "insufficient_data"
