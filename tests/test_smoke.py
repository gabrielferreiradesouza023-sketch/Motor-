"""All numbers/IDs/invoices are synthetic; FakeMeta forbids every write."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.meta.read import Reader
from arb.meta.sync import sync
from arb.models import Action, Decision, Entity, MetricAdjustment, MetricSnapshot, Offer
from arb.remote.fake import FakeMeta
from arb.smoke import ids, markdown, record_invoice, register, report, require_automatic

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def smoke_db(tmp_path, records):
    conn = connect(tmp_path / "smoke.db")
    migrate(conn)
    with conn:
        Repository(conn, Offer).add(records[0])
    yield conn
    conn.close()


def registered(conn, cap=25000):
    return register(conn, "1", "2", ["3"], "offer", "CO", cap, now=NOW)


def sync_fixture(conn):
    fake = FakeMeta(on_call=lambda _: pytest.fail("smoke must never write"))
    fake.entities = {
        e.meta_id: e.model_copy(update={"status": "active"})
        for e in Repository(conn, Entity).list()
    }
    calls = []

    def respond(req):
        calls.append(req.method)
        assert req.method == "GET"
        if req.url.path.endswith("/ads"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "3",
                            "status": fake.read("3").status.upper(),
                            "adset": {
                                "id": "2",
                                "status": "ACTIVE",
                                "daily_budget": "1000",
                                "campaign": {"id": "1", "status": "ACTIVE"},
                            },
                        }
                    ]
                },
            )
        if req.url.path.endswith("/insights"):
            period = json.loads(req.url.params["time_range"])["since"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "ad_id": "3",
                            "date_start": period,
                            "date_stop": period,
                            "impressions": "2000",
                            "inline_link_clicks": "40",
                            "spend": "20.00",
                            "actions": [{"action_type": "video_view", "value": "600"}],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    reader = Reader(
        "synthetic", "123", "v99.0", client=httpx.Client(transport=httpx.MockTransport(respond))
    )
    for offset in range(3):
        day = date(2026, 10, 5) + timedelta(days=offset)
        sync(conn, reader, day, day, now=NOW + timedelta(days=offset))
    assert fake.calls == [] and len(calls) == 9
    return fake


def test_three_days_sync_csv_and_numerical_report(smoke_db, tmp_path):
    registered(smoke_db, cap=6000)
    fake = sync_fixture(smoke_db)
    from arb.tracker import import_sales

    csv = tmp_path / "synthetic-sales.csv"
    csv.write_text(
        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
        "tx1,2026-10-05T12:00:00Z,5000,approved,3\n"
        "tx2,2026-10-05T12:00:00Z,5000,approved,unmatched\n"
    )
    import_sales(smoke_db, csv)
    with smoke_db:
        Repository(smoke_db, MetricSnapshot).add(
            MetricSnapshot(
                entity_id="meta-3",
                ts=NOW + timedelta(hours=1),
                impressions=0,
                video_3s_views=0,
                link_clicks=0,
                spend_platform_cents=0,
                bridge_views=150,
                checkout_clicks=30,
            )
        )
        Repository(smoke_db, MetricAdjustment).add(
            MetricAdjustment(
                id="correction",
                entity_id="meta-3",
                ts=NOW + timedelta(days=3),
                period_start=date(2026, 10, 5),
                deltas={"spend_platform_cents": -100},
                reason="synthetic",
            )
        )
    row = report(smoke_db)["campaigns"][0]
    assert row["spend_platform_cents"] == 5900 and row["spend_gross"] == 6667
    assert row["cpm_gross"] == pytest.approx(1111.1666666667)
    assert (
        row["ctr_link"] == 0.02 and row["hook_rate"] == 0.3 and row["bridge_checkout_rate"] == 0.2
    )
    assert row["matched_sales"] == 1 and row["matched_transactions"] == 1
    assert report(smoke_db)["unmatched_sales_bank"] == 1
    assert row["checklist"] == {"V-02": "observado", "V-04": "pendente"}
    assert row["alerts"] and row["acceptance_f6"] is False and fake.effects == []
    assert "CPM bruto" in markdown(report(smoke_db))
    assert report(smoke_db) == report(smoke_db)


def test_registration_is_atomic_audited_and_not_f6(smoke_db):
    result = registered(smoke_db)
    assert result["entities"] == ["meta-1", "meta-2", "meta-3"]
    action = Repository(smoke_db, Action).list()[0]
    assert (
        action.actor == "human"
        and action.live is False
        and action.payload_json["acceptance_f6"] is False
    )
    assert smoke_db.execute("SELECT count(*) FROM acceptance_test_entities").fetchone()[0] == 0
    assert all(e.gate == "0" and e.status == "paused" for e in Repository(smoke_db, Entity).list())
    assert report(smoke_db)["campaigns"][0]["cpm_gross"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"ads": []},
        {"ads": ["2"]},
        {"campaign": "bad"},
        {"geo": "col"},
        {"cap_cents": 0},
        {"cap_cents": True},
        {"offer_id": "unknown"},
        {"now": datetime(2026, 10, 5)},
    ],
)
def test_invalid_registration_leaves_no_entities(smoke_db, patch):
    args = (
        dict(
            campaign="1", adset="2", ads=["3"], offer_id="offer", geo="CO", cap_cents=25000, now=NOW
        )
        | patch
    )
    with pytest.raises(ValueError):
        register(smoke_db, **args)
    assert Repository(smoke_db, Entity).list() == [] and Repository(smoke_db, Action).list() == []


def test_duplicate_and_pending_transaction_refused(smoke_db):
    registered(smoke_db)
    before = list(smoke_db.iterdump())
    with pytest.raises(ValueError, match="já registrados"):
        registered(smoke_db)
    assert list(smoke_db.iterdump()) == before
    smoke_db.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        registered(smoke_db)
    smoke_db.rollback()


@pytest.mark.parametrize("operation", ["pause", "activate", "scale", "journal", "f6", "ancestor"])
def test_automatic_paths_never_reach_writer(smoke_db, operation):
    registered(smoke_db)
    fake = sync_fixture(smoke_db)
    from arb.accept_pause import eligible
    from arb.launcher.actions import activate, pause
    from arb.launcher.scale import check
    from arb.remote.journal import perform

    entity = Repository(smoke_db, Entity).get("meta-3")
    with pytest.raises(ValueError, match="smoke"):
        if operation == "pause":
            pause(smoke_db, entity.id, reason="test", writer=fake)
        elif operation == "activate":
            activate(smoke_db, entity.id, "none", writer=fake)
        elif operation == "scale":
            check(smoke_db, Repository(smoke_db, Entity).get("meta-2"), 1200, NOW)
        elif operation == "journal":
            perform(smoke_db, fake, entity, "pause", "key", context={}, now=NOW)
        elif operation == "f6":
            eligible(smoke_db, "3", flagged=False)
        else:
            with smoke_db:
                e = Entity(
                    id="outside",
                    kind="campaign",
                    offer_id="offer",
                    geo="CO",
                    gate="0",
                    status="active",
                    daily_budget_cents=0,
                )
                Repository(smoke_db, Entity).add(e)
                e = Repository(smoke_db, Entity).get("meta-1")
                e.parent_id = "outside"
                Repository(smoke_db, Entity).update(e)
            pause(smoke_db, "outside", reason="test", writer=fake)
    assert fake.calls == [] and fake.effects == []


def test_scheduler_stale_and_financial_brakes_only_alert_human(smoke_db, tmp_path):
    registered(smoke_db, cap=1)
    fake = sync_fixture(smoke_db)
    from arb.scheduler import run_cycle, schedule

    with smoke_db:
        e = Repository(smoke_db, Entity).get("meta-3")
        e.gate = "3"
        Repository(smoke_db, Entity).update(e)
    slot = schedule(date(2026, 10, 8), date(2026, 10, 8))[0]
    result = run_cycle(
        smoke_db, slot, now=slot, root=ROOT, output=tmp_path / "reports", writer=fake
    )
    assert result["decisions"] == [] and result["pauses"] == []
    assert any("smoke_cap_reached" in a for a in result["alerts"])
    assert Repository(smoke_db, Decision).list() == []
    assert Repository(smoke_db, Entity).get("meta-3").status == "active" and fake.calls == []


def test_new_descendants_remain_protected_and_unrelated_entity_allowed(smoke_db):
    registered(smoke_db)
    with smoke_db:
        for name, parent in [("new", "meta-2"), ("unrelated", None)]:
            Repository(smoke_db, Entity).add(
                Entity(
                    id=name,
                    kind="ad",
                    parent_id=parent,
                    offer_id="offer",
                    geo="CO",
                    gate="1",
                    status="active",
                    daily_budget_cents=1000,
                )
            )
    assert "new" in ids(smoke_db)
    with pytest.raises(ValueError, match="smoke"):
        require_automatic(smoke_db, "new")
    require_automatic(smoke_db, "unrelated")


def test_invoice_observed_only_when_same_cumulative_spend(smoke_db):
    registered(smoke_db)
    sync_fixture(smoke_db)
    record_invoice(smoke_db, "meta-1", 6000, 6780, "synthetic invoice", now=NOW)
    row = report(smoke_db)["campaigns"][0]
    assert (
        row["implicit_tax_rate"] == pytest.approx(0.13) and row["checklist"]["V-04"] == "observado"
    )
    record_invoice(
        smoke_db, "meta-1", 5000, 5650, "synthetic stale invoice", now=NOW + timedelta(days=1)
    )
    assert report(smoke_db)["campaigns"][0]["implicit_tax_rate"] is None
    assert report(smoke_db)["campaigns"][0]["checklist"]["V-04"] == "pendente"
    with pytest.raises(ValueError, match="desconhecida"):
        report(smoke_db, "unknown")


@pytest.mark.parametrize(
    "args",
    [
        ("meta-1", 0, 1, "ref"),
        ("meta-1", 1, -1, "ref"),
        ("meta-1", 1, 1, ""),
        ("unknown", 1, 1, "ref"),
    ],
)
def test_invoice_invalid_refused(smoke_db, args):
    registered(smoke_db)
    with pytest.raises(ValueError):
        record_invoice(smoke_db, *args)
    smoke_db.execute("BEGIN")
    with pytest.raises(ValueError, match="commit"):
        record_invoice(smoke_db, "meta-1", 1, 1, "ref")
    smoke_db.rollback()


def test_acceptance_entities_excluded_from_report(smoke_db):
    registered(smoke_db)
    sync_fixture(smoke_db)
    with smoke_db:
        smoke_db.execute("INSERT INTO acceptance_test_entities VALUES (?,?)", ("meta-3", "3"))
    assert report(smoke_db)["campaigns"][0]["spend_gross"] == 0


def test_cli_registration_invoice_and_readonly_report(smoke_db, tmp_path):
    database = smoke_db.execute("PRAGMA database_list").fetchone()[2]
    runner = CliRunner()
    args = ["--database", database]
    value = runner.invoke(
        app,
        [
            "smoke",
            "register",
            "--campaign",
            "1",
            "--adset",
            "2",
            "--ad",
            "3",
            "--offer",
            "offer",
            "--geo",
            "CO",
            "--cap-cents",
            "25000",
            *args,
        ],
    )
    assert value.exit_code == 0, value.output
    assert (
        runner.invoke(
            app,
            [
                "smoke",
                "register",
                "--campaign",
                "1",
                "--adset",
                "2",
                "--ad",
                "3",
                "--offer",
                "offer",
                "--geo",
                "CO",
                "--cap-cents",
                "25000",
                *args,
            ],
        ).exit_code
        == 2
    )
    result = runner.invoke(
        app,
        [
            "smoke",
            "invoice",
            "--campaign",
            "1",
            "--platform-cents",
            "1",
            "--total-cents",
            "1",
            "--evidence-ref",
            "synthetic",
            *args,
        ],
    )
    assert result.exit_code == 0, result.output
    assert (
        runner.invoke(
            app,
            [
                "smoke",
                "invoice",
                "--campaign",
                "9",
                "--platform-cents",
                "1",
                "--total-cents",
                "1",
                "--evidence-ref",
                "synthetic",
                *args,
            ],
        ).exit_code
        == 2
    )
    before = list(smoke_db.iterdump())
    result = runner.invoke(
        app,
        [
            "smoke",
            "report",
            "--campaign",
            "1",
            *args,
            "--output",
            str(tmp_path / "r.json"),
            "--report-file",
            str(tmp_path / "r.md"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert list(smoke_db.iterdump()) == before
    assert json.loads((tmp_path / "r.json").read_text())["signed_acceptance"] is False
    for output, md in [
        (database, str(tmp_path / "safe.md")),
        (str(tmp_path / "safe.json"), database),
        ("config/forbidden.json", str(tmp_path / "x.md")),
        (str(tmp_path / "same"), str(tmp_path / "same")),
    ]:
        assert (
            runner.invoke(
                app, ["smoke", "report", *args, "--output", output, "--report-file", md]
            ).exit_code
            == 2
        )


def test_reparented_ad_is_not_double_counted_between_smoke_campaigns(smoke_db):
    registered(smoke_db)
    sync_fixture(smoke_db)
    register(smoke_db, "4", "5", ["6"], "offer", "CO", 25000, now=NOW)
    with smoke_db:
        ad = Repository(smoke_db, Entity).get("meta-3")
        ad.parent_id = "meta-5"
        Repository(smoke_db, Entity).update(ad)
    rows = report(smoke_db)["campaigns"]
    assert [r["spend_platform_cents"] for r in rows] == [0, 6000]
    assert sum(r["spend_gross"] for r in rows) == 6780
    assert "meta-3" in ids(smoke_db)  # Still protected even after hierarchy changes.


def test_missing_or_cyclic_parent_still_protects_original_binding(smoke_db):
    registered(smoke_db)
    sync_fixture(smoke_db)
    with smoke_db:
        ad = Repository(smoke_db, Entity).get("meta-3")
        ad.parent_id = None
        Repository(smoke_db, Entity).update(ad)
    assert report(smoke_db)["campaigns"][0]["spend_platform_cents"] == 6000
    with smoke_db:
        ad.parent_id = ad.id
        Repository(smoke_db, Entity).update(ad)
    assert report(smoke_db)["campaigns"][0]["spend_platform_cents"] == 6000
