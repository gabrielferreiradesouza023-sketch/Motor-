"""Independent cent references and planted premature own-refund samples."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from test_scout_producer import own_sales

from arb.analyst import pnl
from arb.config import load_settings
from arb.db import Repository, connect, migrate
from arb.metrics import effective_refund_rate, effective_refund_rates, rev_expected
from arb.models import Decision, Entity, Offer
from arb.rules import evaluate, load_rules
from arb.scout import import_adlibrary, import_offers
from arb.scout.ranking import producer_report, rank

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "declared,rate,revenue,cap",
    [
        (None, 0.15, 5100, 15300),
        (0.05, 0.15, 5100, 15300),
        (0.10, 0.15, 5100, 15300),
        (0.15, 0.15, 5100, 15300),
        (0.20, 0.20, 4800, 14400),
    ],
)
def test_commission_and_g3_cap_independent_cent_references(records, declared, rate, revenue, cap):
    offer = records[0].model_copy(
        update={"commission_brl_cents": 6000, "producer_refund_rate": declared}
    )
    sales = own_sales(records, 1, 0)
    effective = effective_refund_rate(offer, sales)
    assert effective == rate
    assert rev_expected(sales, effective) == revenue
    decision = evaluate(
        records[3].model_copy(update={"gate": "3"}),
        records[4],
        sales,
        6000,
        load_rules(),
        records[4].ts,
        refund_rate=effective,
    )
    assert decision.metrics_json["cap_cents"] == cap


def test_nineteen_twenty_boundary_replay_and_own_refund_without_floor(records):
    offer = records[0].model_copy(update={"producer_refund_rate": 0.05})
    sales = own_sales(records, 20, 2)
    assert effective_refund_rate(offer, sales[:19]) == 0.15
    replay = sales[18].model_copy(update={"id": "new-receipt-id"})
    assert effective_refund_rate(offer, sales[:19] + [replay] * 10) == 0.15
    assert effective_refund_rate(offer, sales) == 0.10  # 2/20, no floor
    assert rev_expected([sales[2]], 0.10) == 5400  # commission 6000 * .90


def test_foreign_unmatched_and_test_receipts_cannot_push_over_twenty(records):
    offer = records[0].model_copy(update={"producer_refund_rate": 0.05})
    own = records[3]
    sibling = own.model_copy(update={"id": "sibling"})
    foreign = own.model_copy(update={"id": "foreign", "offer_id": "another"})
    acceptance = own.model_copy(update={"id": "acceptance"})
    another = offer.model_copy(update={"id": "another", "producer_refund_rate": None})
    sales = own_sales(records, 19, 2)
    last = own_sales(records, 20, 2)[19]
    noise = [
        last.model_copy(update={"id": "foreign", "matched_entity_id": "foreign"}),
        last.model_copy(update={"id": "unmatched", "matched_entity_id": None}),
        last.model_copy(update={"id": "test", "matched_entity_id": "acceptance"}),
        sales[18].model_copy(update={"id": "replay"}),
    ]
    entities = [own, sibling, foreign, acceptance]
    rates = effective_refund_rates(
        [offer, another], entities, sales + noise, exclude_ids={"acceptance"}
    )
    assert rates[own.id] == rates[sibling.id] == 0.15 and "foreign" not in rates
    rates = effective_refund_rates(
        [offer],
        entities,
        sales + noise + [last.model_copy(update={"matched_entity_id": "sibling"})],
        exclude_ids={"acceptance"},
    )
    assert rates[own.id] == rates[sibling.id] == 0.10


@pytest.mark.parametrize("default,minimum,expected", [(0.25, 20, 0.25), (0.25, 2, 0.5)])
def test_settings_parameters_override_literal_defaults(
    records, monkeypatch, default, minimum, expected
):
    import arb.metrics as module

    configured = load_settings().model_copy(
        update={"refund_rate": default, "refund_min_sales": minimum}
    )
    monkeypatch.setattr(module, "load_settings", lambda: configured)
    offer = records[0].model_copy(update={"producer_refund_rate": 0.10})
    sales = own_sales(records, 2, 1)
    assert effective_refund_rate(offer, sales) == expected
    assert effective_refund_rate(offer, sales, default=default, min_sales=minimum) == expected
    assert effective_refund_rate(offer, sales, min_sales=minimum) == expected
    assert effective_refund_rate(offer, sales, default=default) == expected


@pytest.mark.parametrize(
    "declared,basis",
    [
        (0.05, "producer_floor"),
        (0.10, "producer_floor"),
        (0.15, "producer"),
        (0.20, "producer"),
        (None, "default"),
    ],
)
def test_ranking_floor_and_report_explain_reference(records, declared, basis):
    from arb.models import OfferIntake

    offer = records[0].model_copy(
        update={
            "commission_brl_cents": 6000,
            "producer_paid_traffic_ok": True,
            "evidence_ref": "SYNTHETIC permission",
            "producer_refund_rate": declared,
            "advertisers_30d": 5,
        }
    )
    intake = [
        OfferIntake(
            offer=offer, native_spanish=True, sales_page_quality=5, popularity=60, policy_risk=0
        )
    ]
    ranked, rejected = rank(intake, [])
    # weights: commission 30*.51 or *.48, market 25, page 15, popularity 15*.6, /85
    assert not rejected and ranked[0].score == (74.59 if declared == 0.20 else 75.65)
    assert producer_report(intake)[offer.id]["commission_refund_basis"] == basis
    settings = load_settings().model_copy(update={"refund_rate": 0.25})
    assert producer_report(intake, settings=settings)[offer.id]["commission_refund_basis"] == (
        "default" if declared is None else "producer_floor"
    )
    assert rank(intake, [], settings=settings)[0][0].score == 73.53


def test_old_csv_ranking_full_json_is_byte_identical():
    intake = import_offers(ROOT / "examples/scout/offers.csv")
    ranked, rejected = rank(intake, import_adlibrary(ROOT / "examples/scout/adlibrary.csv"))
    actual = (
        json.dumps(
            {
                "offers": [o.model_dump(mode="json") for o in ranked],
                "rejected": rejected,
                "producer": producer_report(intake),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    assert actual == (ROOT / "tests/fixtures/refund/legacy-ranking.json").read_text()


def test_scheduler_and_pnl_use_same_configured_floor_and_sample_minimum(tmp_path, records):
    from unittest.mock import patch

    import arb.analyst as analyst
    from arb.scheduler import run_cycle, schedule

    root = tmp_path / "root"
    shutil.copytree(ROOT / "config", root / "config")
    settings = load_settings().model_copy(update={"refund_rate": 0.25, "refund_min_sales": 3})
    (root / "config/settings.yaml").write_text(yaml.safe_dump(settings.model_dump()))
    db = connect(tmp_path / "data.db")
    migrate(db)
    try:
        with db:
            Repository(db, Offer).add(
                records[0].model_copy(
                    update={"commission_brl_cents": 6000, "producer_refund_rate": 0.10}
                )
            )
            Repository(db, Entity).add(
                records[3].model_copy(
                    update={"gate": "3", "status": "active", "creative_id": None, "angle_id": None}
                )
            )
            Repository(db, type(records[4])).add(records[4])
            for sale in own_sales(records, 2, 0):
                Repository(db, type(sale)).add(sale)
        with patch.object(analyst, "load_settings", return_value=settings):
            assert pnl(db)["totals"]["rev_expected"] == 9000  # 2 * 6000 * .75
        slot = schedule(records[4].ts.date(), records[4].ts.date())[0]
        value = run_cycle(
            db, slot, now=slot, root=root, output=tmp_path / "reports", sync_source=lambda c, n: n
        )
        d = Repository(db, Decision).get(value["decisions"][0])
        assert d.metrics_json["cap_cents"] == 13500 and d.metrics_json["rev_expected"] == 9000
        assert "R$ 90.00" in Path(value["report"]).read_text()
        # Lower configured sample threshold: three own approved transactions => observed zero.
        with db:
            Repository(db, type(records[5])).add(own_sales(records, 3, 0)[2])
            Repository(db, type(records[4])).add(
                records[4].model_copy(update={"ts": slot.replace(hour=18)})
            )
        assert (
            pnl(db, refund_rate=settings.refund_rate, refund_min_sales=3)["totals"]["rev_expected"]
            == 18000
        )
        next_slot = schedule(records[4].ts.date(), records[4].ts.date())[1]
        value = run_cycle(
            db,
            next_slot,
            now=next_slot,
            root=root,
            output=tmp_path / "reports",
            sync_source=lambda c, n: n,
        )
        d = Repository(db, Decision).get(value["decisions"][0])
        assert d.metrics_json["cap_cents"] == 18000 and d.metrics_json["rev_expected"] == 18000
        assert "R$ 180.00" in Path(value["report"]).read_text()
    finally:
        db.close()
