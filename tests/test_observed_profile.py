"""Entire dataset is synthetic; expected aggregate values are hand-counted."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from arb.cli import app
from arb.config import Settings, load_profile_file
from arb.db import Repository, connect, migrate
from arb.models import Entity, MetricAdjustment, MetricSnapshot, SaleEvent
from arb.rules import load_rules
from arb.sim.calibrate import calibrate
from arb.sim.observed import profile, wilson, window, write_profile

SINCE = "2026-10-05"
UNTIL = "2026-10-07"


def settings():
    return Settings.model_validate(yaml.safe_load(Path("config/settings.yaml").read_text()))


@pytest.fixture
def observed_db(tmp_path, records):
    connection = connect(tmp_path / "synthetic.db")
    migrate(connection)
    with connection:
        for record in records[:4]:
            Repository(connection, type(record)).add(record)
        for day in range(3):
            ts = records[4].ts + timedelta(days=day)
            Repository(connection, MetricSnapshot).add(
                records[4].model_copy(
                    update={
                        "ts": ts,
                        "period_start": ts.date(),
                        "impressions": 2000,
                        "video_3s_views": 600,
                        "link_clicks": 40,
                        "spend_platform_cents": 2000,
                        "bridge_views": 50,
                        "checkout_clicks": 10,
                    }
                )
            )
            for sale in range(3):
                identifier = f"synthetic-{day}-{sale}"
                Repository(connection, SaleEvent).add(
                    records[5].model_copy(
                        update={"id": identifier, "hotmart_tx_id": identifier, "ts": ts}
                    )
                )
    yield connection
    connection.close()


def run(connection, since=SINCE, until=UNTIL, **kwargs):
    return profile(
        connection, since, until, rules=kwargs.get("rules", load_rules()), settings=settings()
    )


def test_reference_window_rates_and_rounding(observed_db, tmp_path):
    result = run(observed_db)
    row = result["geos"]["CO"]
    assert row["status"] == "sufficient"
    assert row["samples"]["impressions"] == 6000 and row["samples"]["sales"] == 9
    assert row["cpm_gross_cents"] == 1130
    assert row["rates"]["ctr"]["estimate"] == 0.02
    assert row["rates"]["hook"]["estimate"] == 0.3
    assert row["rates"]["checkout"]["estimate"] == 0.2
    assert row["rates"]["purchase"]["estimate"] == 0.3
    assert row["rates"]["checkout"]["interval90"] == pytest.approx(
        [0.15180789275671334, 0.25882254040071316], abs=1e-12
    )
    out = tmp_path / "reports/observed.yaml"
    write_profile(result, out)
    first = out.read_bytes()
    write_profile(run(observed_db), out)
    assert out.read_bytes() == first
    loaded = load_profile_file(out)
    assert list(loaded) == ["observed_CO"]
    assert loaded["observed_CO"].winner == loaded["observed_CO"].loser
    assert loaded["observed_CO"].winner.cpm_cents == (979, 1022)
    calibrated = calibrate(grid={"gate_3.min_sales": [2]}, seeds=[0], profile_file=out)
    assert calibrated["profiles"] == ["observed_CO"] and len(calibrated["rows"]) == 1
    assert "local_sqlite" in first.decode() and "samples" in first.decode()


def test_test_entities_and_period_corrections_excluded(observed_db, records):
    with observed_db:
        e = records[3].model_copy(update={"id": "synthetic-test", "meta_id": "123"})
        Repository(observed_db, Entity).add(e)
        observed_db.execute("INSERT INTO acceptance_test_entities VALUES (?,?)", (e.id, e.meta_id))
        Repository(observed_db, MetricSnapshot).add(
            records[4].model_copy(
                update={"entity_id": e.id, "impressions": 999999, "spend_platform_cents": 999999}
            )
        )
        Repository(observed_db, SaleEvent).add(
            records[5].model_copy(
                update={"id": "excluded", "hotmart_tx_id": "excluded", "matched_entity_id": e.id}
            )
        )
        Repository(observed_db, MetricAdjustment).add(
            MetricAdjustment(
                id="correction",
                entity_id="entity",
                ts=datetime(2026, 10, 10, tzinfo=UTC),
                period_start=date(2026, 10, 5),
                deltas={"impressions": -100, "spend_platform_cents": -100},
                reason="synthetic corrected period",
            )
        )
    row = run(observed_db)["geos"]["CO"]
    assert row["samples"]["impressions"] == 5900 and row["samples"]["sales"] == 9
    assert row["cpm_gross_cents"] == 1130


def receipt(conn, records, identifier, kind, *, test=False, source="synthetic"):
    body = {
        "id": identifier,
        "ad_id": "entity",
        "geo": "CO",
        "kind": kind,
        "ts": records[4].ts.isoformat(),
    }
    if test:
        body["test"] = True
    conn.execute(
        "INSERT INTO tracker_receipts VALUES (?,?,?,1)", (source, identifier, json.dumps(body))
    )


def test_receipts_override_derived_snapshots_and_tests_do_not_count(observed_db, records):
    with observed_db:
        for n in range(150):
            receipt(observed_db, records, "v" + str(n), "view")
        for n in range(30):
            receipt(observed_db, records, "c" + str(n), "checkout_click")
        receipt(observed_db, records, "synthetic-test", "checkout_click", test=True)
        receipt(observed_db, records, "v0", "view", source="replica")
    row = run(observed_db)["geos"]["CO"]
    assert row["samples"]["bridge_views"] == 150
    assert row["samples"]["checkout_clicks"] == 30
    assert row["bridge_source"] == "receipts"
    with observed_db:
        receipt(observed_db, records, "v0", "checkout_click", source="conflict")
    with pytest.raises(ValueError, match="conflitante"):
        run(observed_db)


@pytest.mark.parametrize(
    "case", ["empty_window", "small", "zero_cost", "invalid_funnel", "subcent", "tiny_poisson"]
)
def test_insufficient_data_is_not_invented(observed_db, case, tmp_path):
    rules = load_rules()
    if case == "empty_window":
        result = run(observed_db, "2020-01-01", "2020-01-02")
    else:
        # Replace only the synthetic connection with a new database, retaining no old observations.
        other = connect(tmp_path / "small.db")
        migrate(other)
        from arb.models import Offer

        offer = Repository(observed_db, Offer).get("offer")
        entity = (
            Repository(observed_db, Entity)
            .get("entity")
            .model_copy(update={"angle_id": None, "creative_id": None})
        )
        base = Repository(observed_db, MetricSnapshot).list()[0]
        sale = Repository(observed_db, SaleEvent).list()[0]
        changes = (
            {"impressions": 500, "video_3s_views": 150}
            if case == "small"
            else {"spend_platform_cents": 0}
            if case == "zero_cost"
            else {"link_clicks": 3000}
            if case == "invalid_funnel"
            else {"spend_platform_cents": 1, "impressions": 10000}
            if case == "subcent"
            else {"impressions": 1, "link_clicks": 1, "video_3s_views": 1}
        )
        if case == "tiny_poisson":
            rules = rules.model_copy(
                update={"gate_1": rules.gate_1.model_copy(update={"min_impressions": 1})}
            )
        with other:
            Repository(other, Offer).add(offer)
            Repository(other, Entity).add(entity)
            Repository(other, MetricSnapshot).add(base.model_copy(update=changes))
            for n in range(3):
                Repository(other, SaleEvent).add(
                    sale.model_copy(update={"id": str(n), "hotmart_tx_id": str(n)})
                )
        result = run(other, rules=rules)
        other.close()
    row = result["geos"]["CO"]
    assert row["status"] == "insufficient_data" and "distribution" not in row and "rates" not in row
    out = write_profile(result, tmp_path / "reports/insufficient.yaml")
    with pytest.raises(ValueError, match="insufficient_data"):
        load_profile_file(out)


def test_empty_database_and_no_mutation(tmp_path):
    connection = connect(tmp_path / "empty.db")
    migrate(connection)
    result = run(connection)
    assert result["geos"] == {}
    out = write_profile(result, tmp_path / "reports/empty.yaml")
    assert yaml.safe_load(out.read_text()) == {"observed": {"status": "insufficient_data"}}
    connection.close()


@pytest.mark.parametrize(
    "since,until",
    [
        ("2026-10-05T12:00:00", "2026-10-06"),
        ("2026-10-08", "2026-10-07"),
        ("invalid", "2026-10-07"),
        ("2026-10-05T12:00:00Z", "2026-10-05T12:00:00Z"),
    ],
)
def test_invalid_window(since, until):
    with pytest.raises(ValueError):
        window(since, until)


@pytest.mark.parametrize("k,n", [(1, 0), (-1, 2), (3, 2)])
def test_wilson_invalid(k, n):
    with pytest.raises(ValueError):
        wilson(k, n)


def test_full_timestamp_window_and_endpoint_reference():
    assert window("2026-10-05T09:00:00-03:00", "2026-10-06T12:00:00Z") == (
        datetime(2026, 10, 5, 12, tzinfo=UTC),
        datetime(2026, 10, 6, 12, tzinfo=UTC),
    )
    assert wilson(0, 100)[0] == 0 and wilson(100, 100)[1] == 1


@pytest.mark.parametrize("case", ["config", "symlink"])
def test_output_config_or_link_refused(observed_db, tmp_path, case):
    target = tmp_path / "config/file.yaml"
    target.parent.mkdir()
    target.write_text("synthetic sentinel")
    output = target
    if case == "symlink":
        output = tmp_path / "link.yaml"
        output.symlink_to(target)
    with pytest.raises(ValueError):
        write_profile(run(observed_db), output)
    assert target.read_text() == "synthetic sentinel"


@pytest.mark.parametrize("body", ["[]", "{}", "{wrong: 1}", "{1: {}}", "{wrong: {}}"])
def test_invalid_profile_files(tmp_path, body):
    path = tmp_path / "bad.yaml"
    path.write_text(body)
    with pytest.raises(ValueError):
        load_profile_file(path)


def test_cli_readonly_profile_and_calibration(observed_db, tmp_path):
    path = Path(observed_db.execute("PRAGMA database_list").fetchone()[2])
    before = list(observed_db.iterdump())
    output = tmp_path / "reports/observed.yaml"
    result = CliRunner().invoke(
        app,
        [
            "observed",
            "profile",
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--database",
            str(path),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.exists() and list(observed_db.iterdump()) == before
    import arb.sim.calibrate as module

    # Narrow grid, actual CLI and lab execution; no outcome mocked.
    original = module.GRID
    module.GRID = {"gate_3.min_sales": [2]}
    try:
        result = CliRunner().invoke(
            app,
            [
                "sim",
                "calibrate",
                "--profile-file",
                str(output),
                "--seeds",
                "1",
                "--workers",
                "1",
                "--output",
                str(tmp_path / "calibration.json"),
                "--report",
                str(tmp_path / "calibration.html"),
            ],
        )
        assert result.exit_code == 0, result.output
    finally:
        module.GRID = original
    failed = CliRunner().invoke(
        app,
        [
            "observed",
            "profile",
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--database",
            str(tmp_path / "absent.db"),
        ],
    )
    assert failed.exit_code != 0 and not (tmp_path / "absent.db").exists()


def test_account_day_boundary_does_not_include_previous_day_sales(observed_db, records):
    with observed_db:
        Repository(observed_db, SaleEvent).add(
            records[5].model_copy(
                update={
                    "id": "previous-local-day",
                    "hotmart_tx_id": "previous-local-day",
                    "ts": datetime(2026, 10, 5, 2, 59, 59, tzinfo=UTC),
                }
            )
        )
    result = run(observed_db)
    assert result["window"]["since"] == "2026-10-05T03:00:00+00:00"
    assert result["window"]["until_exclusive"] == "2026-10-08T03:00:00+00:00"
    assert result["geos"]["CO"]["samples"]["sales"] == 9


def test_observed_calibration_cannot_call_a_nominal_loser_winner(
    observed_db, tmp_path, monkeypatch
):
    from dataclasses import replace

    import arb.sim.calibrate as module
    from arb.sim import population
    from arb.sim.lab import Run

    output = write_profile(run(observed_db), tmp_path / "reports/observed.yaml")
    p = population(42)
    for identifier, truth in p.truth.items():
        p.truth[identifier] = replace(truth, purchase=0.000001)
    fake = Run(42, p, winners=["o0-a0"])  # luck/nominal winner, expected net return is negative
    monkeypatch.setattr(module, "run_lab", lambda *args, **kwargs: fake)
    result = calibrate(grid={"gate_3.min_sales": [2]}, seeds=[42], profile_file=output)
    assert result["rows"][0]["winner_found_rate"] == 0
    assert result["rows"][0]["borderline_found_rate"] is None
