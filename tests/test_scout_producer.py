"""Synthetic producer data; independent formulas and permission violations."""

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arb.analyst import pnl
from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.launcher import plan
from arb.metrics import effective_refund_rate, effective_refund_rates, rev_expected, summarize
from arb.models import PRODUCER_FIELDS, Entity, Offer, OfferIntake, SaleEvent
from arb.rules import evaluate, load_rules
from arb.scout import import_adlibrary, import_offers
from arb.scout.ranking import producer_offer, producer_report, propose, rank

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "examples/scout/offers.csv"


def csv_with(tmp_path, extra):
    with OLD.open() as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames
        rows = list(reader)
    rows[0].update(extra)
    path = tmp_path / "synthetic-producer.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, headers + list(extra))
        writer.writeheader()
        writer.writerows(rows)
    return path


def own_sales(records, count=20, refunds=4, entity="entity"):
    return [
        records[5].model_copy(
            update={
                "id": f"own-{i}",
                "hotmart_tx_id": f"tx-{i}",
                "commission_cents": 6000,
                "status": "refunded" if i < refunds else "approved",
                "matched_entity_id": entity,
            }
        )
        for i in range(count)
    ]


def test_old_csv_serialization_ranking_and_cap_reference(records):
    intake = import_offers(OLD)
    ads = import_adlibrary(ROOT / "examples/scout/adlibrary.csv")
    ranked, rejected = rank(intake, ads)
    # Reference: CSV commission*.85, 1 advertiser/5, page quality, popularity;
    # weights 30/25/15/15, denominator 85, risk penalty -15.
    assert [(o.id, o.score) for o in ranked] == [
        ("excel", 54.15),
        ("pets", 44.97),
        ("croche", 44.09),
    ]
    assert "blocked" in rejected and producer_report(intake) == {}
    for item in intake:
        assert all(
            key not in item.offer.model_dump() and key not in item.model_dump()
            for key in PRODUCER_FIELDS
        )
        assert (
            Offer.model_validate(item.offer.model_dump()).model_dump_json()
            == item.offer.model_dump_json()
        )
    offer = records[0]
    assert effective_refund_rate(offer, own_sales(records), 0.15) == 0.15
    decision = evaluate(
        records[3].model_copy(update={"gate": "3"}),
        records[4],
        [],
        5000,
        load_rules(),
        records[4].ts,
    )
    assert decision.metrics_json["cap_cents"] == 12750


def test_permission_false_eliminates_and_cannot_plan_even_with_legacy_true(tmp_path, records):
    item = import_offers(csv_with(tmp_path, {"producer_paid_traffic_ok": "false"}))[0]
    assert item.offer.allows_paid_traffic is False
    assert rank([item], [])[0] == []
    bad = records[0].model_copy(update={"status": "approved", "producer_paid_traffic_ok": False})
    with pytest.raises(ValueError, match="tráfego pago"):
        plan(bad, [], [], geo="CO", daily_budget_cents=1000, destination_url="https://example.com")


def test_evidence_alert_and_market_proof_reference(tmp_path):
    item = import_offers(
        csv_with(
            tmp_path,
            {
                "producer_paid_traffic_ok": "true",
                "producer_refund_rate": ".2",
                "producer_conversion_rate": ".02",
                "advertisers_30d": "5",
                "evidence_ref": "",
            },
        )
    )[0]
    offer = item.offer.model_copy(update={"commission_brl_cents": 5000})
    item = item.model_copy(
        update={"offer": offer, "sales_page_quality": 5, "popularity": 60.0, "policy_risk": 0.0}
    )
    ranked, _ = rank([item], [])
    # (30*.4 + 25*1 + 15*1 + 15*.6)/85 *100; no new weights.
    assert ranked[0].score == 71.76
    info = producer_report([item])[offer.id]
    assert info["alerts"] and info["declared"]["producer_conversion_rate"] == 0.02
    assert info["market_proof_basis"] == "producer" and info["evidence_verified"] is False
    item = item.model_copy(update={"evidence_ref": "synthetic written permission"})
    assert producer_report([item])[offer.id]["alerts"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("producer_refund_rate", "-0.1"),
        ("producer_refund_rate", "1.1"),
        ("producer_refund_rate", "nan"),
        ("producer_conversion_rate", "-0.1"),
        ("producer_conversion_rate", "1.1"),
        ("producer_conversion_rate", "inf"),
        ("producer_paid_traffic_ok", "TRUE"),
        ("advertisers_30d", "-1"),
        ("advertisers_30d", "2.5"),
    ],
)
def test_invalid_producer_columns_refused(tmp_path, field, value):
    with pytest.raises(ValueError):
        import_offers(csv_with(tmp_path, {field: value}))


def test_empty_optional_columns_preserve_legacy_json(tmp_path):
    path = csv_with(tmp_path, {key: "" for key in PRODUCER_FIELDS})
    assert [i.model_dump_json() for i in import_offers(path)] == [
        i.model_dump_json() for i in import_offers(OLD)
    ]
    with pytest.raises(ValueError):
        import_offers(csv_with(tmp_path, {"unapproved_field": "1"}))
    text = path.read_text()
    path.write_text(text.replace("evidence_ref\n", "evidence_ref,evidence_ref\n"))
    with pytest.raises(ValueError):
        import_offers(path)


@pytest.mark.parametrize("field", ["producer_refund_rate", "producer_conversion_rate"])
def test_model_rates_validate_without_csv(records, field):
    for value in [-0.1, 1.1, float("nan"), True]:
        with pytest.raises(ValueError):
            Offer.model_validate(records[0].model_dump() | {field: value})


def test_intake_nested_data_conflict_refused(records):
    item = OfferIntake(
        offer=records[0].model_copy(update={"producer_refund_rate": 0.2}),
        native_spanish=True,
        sales_page_quality=5,
        popularity=60,
        policy_risk=0,
        producer_refund_rate=0.3,
    )
    with pytest.raises(ValueError, match="conflitantes"):
        producer_offer(item)


def test_producer_refund_changes_revenue_and_g3_cap_reference(records):
    offer = records[0].model_copy(
        update={"commission_brl_cents": 6000, "producer_refund_rate": 0.2}
    )
    sales = own_sales(records, 2, 0)
    rate = effective_refund_rate(offer, sales)
    assert rate == 0.2 and rev_expected(sales, rate) == 9600
    d = evaluate(
        records[3].model_copy(update={"gate": "3"}),
        records[4],
        sales,
        6000,
        load_rules(),
        records[4].ts,
        refund_rate=rate,
    )
    assert d.metrics_json["cap_cents"] == 14400 and d.metrics_json["rev_expected"] == 9600


def test_own_twenty_transactions_switch_and_replay_does_not_inflate(records):
    offer = records[0].model_copy(update={"producer_refund_rate": 0.4})
    sales = own_sales(records)
    assert effective_refund_rate(offer, sales[:19]) == 0.4
    assert effective_refund_rate(offer, sales) == 0.2
    assert (
        effective_refund_rate(offer, sales[:19] + [sales[18].model_copy(update={"id": "replay"})])
        == 0.4
    )
    assert effective_refund_rate(offer, own_sales(records, 20, 0)) == 0
    assert effective_refund_rate(offer, own_sales(records, 20, 20)) == 1


def test_rates_are_per_offer_whole_sample_not_ad_or_test_entities(records):
    offer = records[0].model_copy(update={"producer_refund_rate": 0.4})
    entity = records[3]
    other = entity.model_copy(update={"id": "other"})
    synthetic = entity.model_copy(update={"id": "acceptance"})
    another_offer = offer.model_copy(update={"id": "another", "producer_refund_rate": None})
    foreign = entity.model_copy(update={"id": "foreign", "offer_id": "another"})
    sales = own_sales(records, 19, 4) + [
        own_sales(records, 20, 4)[19].model_copy(update={"matched_entity_id": "other"})
    ]
    rates = effective_refund_rates(
        [offer, another_offer], [entity, other, synthetic, foreign], sales
    )
    assert rates["entity"] == 0.2 and rates["other"] == 0.2 and "foreign" not in rates
    sales[-1].matched_entity_id = "acceptance"
    rates = effective_refund_rates(
        [offer], [entity, synthetic, foreign], sales, exclude_ids={"acceptance"}
    )
    assert rates["entity"] == 0.4
    assert effective_refund_rates([another_offer], [foreign], sales) == {}


def test_mixed_revenue_uses_independent_rate_groups_and_half_up(records):
    sales = [
        records[5].model_copy(update={"commission_cents": 1, "matched_entity_id": "producer"}),
        records[5].model_copy(
            update={
                "id": "old",
                "hotmart_tx_id": "old",
                "commission_cents": 1,
                "matched_entity_id": "old",
            }
        ),
        records[5].model_copy(
            update={"id": "refund", "hotmart_tx_id": "refund", "status": "refunded"}
        ),
    ]
    assert rev_expected(sales, 0.15, refund_rates={"producer": 1.0}) == 1
    assert rev_expected(sales[:2], 0.15) == 2
    assert rev_expected([], refund_rates={"producer": 0.2}) == 0
    assert summarize(records[4], sales, refund_rates={"producer": 1.0})["rev_expected"] == 1


def test_pnl_and_scheduler_apply_offer_rate_to_caps(tmp_path, records):
    from arb.models import Decision
    from arb.scheduler import run_cycle, schedule

    conn = connect(tmp_path / "producer.db")
    migrate(conn)
    try:
        with conn:
            Repository(conn, Offer).add(
                records[0].model_copy(
                    update={"producer_refund_rate": 0.2, "commission_brl_cents": 6000}
                )
            )
            Repository(conn, Entity).add(
                records[3].model_copy(
                    update={"gate": "3", "status": "active", "creative_id": None, "angle_id": None}
                )
            )
            Repository(conn, type(records[4])).add(records[4])
            for sale in own_sales(records, 2, 0):
                Repository(conn, SaleEvent).add(sale)
        result = pnl(conn)
        assert result["totals"]["rev_expected"] == 9600
        slot = schedule(records[4].ts.date(), records[4].ts.date())[0]
        value = run_cycle(
            conn, slot, now=slot, root=ROOT, output=tmp_path / "reports", sync_source=lambda c, n: n
        )
        decision = Repository(conn, Decision).get(value["decisions"][0])
        assert (
            decision.metrics_json["cap_cents"] == 14400
            and decision.metrics_json["rev_expected"] == 9600
        )
        assert result["groups"]["offer"][0]["rev_expected"] == 9600
    finally:
        conn.close()


def test_proposal_persists_metadata_and_cli_explains_changes(tmp_path):
    file = csv_with(
        tmp_path,
        {"producer_paid_traffic_ok": "true", "producer_refund_rate": ".2", "advertisers_30d": "5"},
    )
    intake = import_offers(file)
    ranked, _ = rank(intake, import_adlibrary(ROOT / "examples/scout/adlibrary.csv"))
    conn = connect(tmp_path / "scout.db")
    migrate(conn)
    try:
        original = ranked[0].model_copy(update={key: None for key in PRODUCER_FIELDS})
        with conn:
            Repository(conn, Offer).add(original)
        path = propose(conn, ranked, tmp_path / "pending")
        assert Repository(conn, Offer).get("excel").producer_refund_rate == 0.2
        assert any(
            o.get("producer_refund_rate") == 0.2
            for o in json.loads(path.read_text())["plan"]["offers"]
        )
    finally:
        conn.close()
    result = CliRunner().invoke(
        app,
        [
            "scout",
            "rank",
            "--offers",
            str(file),
            "--adlibrary",
            str(ROOT / "examples/scout/adlibrary.csv"),
            "--database",
            str(tmp_path / "cli.db"),
            "--output",
            str(tmp_path / "cli-pending"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["producer"]["excel"]["alerts"]


def test_new_example_explicitly_synthetic_old_example_untouched():
    example = import_offers(ROOT / "examples/scout/offers-producer.csv")[0]
    assert "SINTÉTICO" in example.offer.name and "SINTÉTICO" in example.evidence_ref
    assert len(import_offers(OLD)) == 4
