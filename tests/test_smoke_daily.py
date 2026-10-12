"""Synthetic daily GET pipeline with independent cents/ratios and planted failures."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import yaml
from typer.testing import CliRunner

import arb.smoke_daily as daily_module
from arb.cli import app
from arb.config import Settings
from arb.db import Repository, connect, migrate
from arb.meta.read import Reader
from arb.models import Action, MetricSnapshot, Offer, SaleEvent
from arb.rules import load_rules
from arb.smoke import register

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture
def daily_case(tmp_path, records, monkeypatch):
    conn = connect(tmp_path / "synthetic.db")
    migrate(conn)
    with conn:
        Repository(conn, Offer).add(records[0])
    register(conn, "1", "2", ["3"], "offer", "CO", 11300, now=NOW)
    with conn:
        Repository(conn, MetricSnapshot).add(
            records[4].model_copy(
                update={
                    "entity_id": "meta-3",
                    "ts": NOW - timedelta(minutes=1),
                    "impressions": 0,
                    "video_3s_views": 0,
                    "link_clicks": 0,
                    "spend_platform_cents": 0,
                    "bridge_views": 100,
                    "checkout_clicks": 20,
                }
            )
        )
    state = {"spend": "80.00", "fail": False, "requests": []}

    def respond(request):
        state["requests"].append(request)
        assert request.method == "GET"
        if state["fail"]:
            raise httpx.ConnectError("SYNTHETIC_TOKEN_SENTINEL", request=request)
        if request.url.path.endswith("/ads"):
            ads = [
                {
                    "id": state.get("ad_id", "3"),
                    "status": "ACTIVE",
                    "adset": {
                        "id": "2",
                        "status": "ACTIVE",
                        "daily_budget": "1000",
                        "campaign": {"id": state.get("ad_campaign", "1"), "status": "ACTIVE"},
                    },
                }
            ]
            if request.url.path.endswith("/act_123/ads") and state.get("foreign"):
                ads.append(
                    {
                        "id": "99",
                        "status": state["foreign"],
                        "adset": {
                            "id": "98",
                            "status": "PAUSED",
                            "campaign": {"id": "97", "status": "PAUSED"},
                        },
                    }
                )
            return httpx.Response(200, json={"data": ads})
        if request.url.params.get("level") == "account":
            if state.get("account_fail"):
                return httpx.Response(500, json={"error": {"code": 1}})
            return httpx.Response(
                200, json={"data": [{"spend": state.get("account_spend", state["spend"])}]}
            )
        if request.url.path.endswith("/insights"):
            period = json.loads(request.url.params["time_range"])["since"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "ad_id": state.get("insight_ad", "3"),
                            "campaign_id": state.get("insight_campaign", "1"),
                            "date_start": period,
                            "date_stop": period,
                            "impressions": "2000",
                            "inline_link_clicks": "40",
                            "spend": state["spend"],
                            "actions": [{"action_type": "video_view", "value": "600"}],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    original = Reader.__init__

    def mocked(self, token, account_id, version, **kwargs):
        original(self, token, account_id, version, client=client, attempts=1, sleep=lambda _: None)

    monkeypatch.setattr(Reader, "__init__", mocked)
    monkeypatch.setattr(daily_module, "datetime", Frozen)
    monkeypatch.setenv("LIVE_MODE", "false")
    monkeypatch.setenv("META_ACCESS_TOKEN", "SYNTHETIC_TOKEN_SENTINEL")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "123")
    monkeypatch.setenv("META_API_VERSION", "v99.0")
    args = {
        "settings": Settings.model_validate(
            yaml.safe_load(Path("config/settings.yaml").read_text())
        ),
        "rules": load_rules(),
        "database": tmp_path / "synthetic.db",
        "output_dir": tmp_path / "out",
    }
    yield conn, state, args
    client.close()
    conn.close()


@pytest.mark.parametrize(
    "platform,gross,code,alert",
    [
        ("79.99", 9039, 0, ""),
        ("80.00", 9040, 0, "ATENÇÃO: prepare-se para pausar"),
        ("100.00", 11300, 2, "PAUSE AGORA NO GERENCIADOR"),
    ],
)
def test_threshold_reference_and_no_writes(daily_case, platform, gross, code, alert):
    conn, state, args = daily_case
    state["spend"] = platform
    result, actual = daily_module.daily(conn, "1", **args)
    row = result["campaigns"][0]
    assert actual == code and row["spend_gross"] == gross
    assert row["cpm_gross"] == gross / 2 and row["ctr_link"] == 0.02 and row["hook_rate"] == 0.3
    assert row["bridge_views"] == 100 and row["checkout_clicks"] == 20
    assert result["daily"]["messages"] == ([alert] if alert else [])
    assert result["daily"]["since"] == "2026-10-10" and result["daily"]["until"] == "2026-10-10"
    assert {r.method for r in state["requests"]} == {"GET"}
    assert not {a.kind for a in Repository(conn, Action).list()} & {
        "pause",
        "activate",
        "scale",
        "launch",
    }
    files = sorted(args["output_dir"].iterdir())
    assert [p.name for p in files] == ["2026-10-10T0900.json", "2026-10-10T0900.md"]
    assert json.loads(files[0].read_text()) == result
    text = daily_module.summary(result)
    assert f"{gross} centavos" in text and "SYNTHETIC_TOKEN_SENTINEL" not in text


def test_replay_csv_explicit_mapping_and_same_window(daily_case, tmp_path):
    conn, state, args = daily_case
    path = tmp_path / "SYNTHETIC-sales.csv"
    path.write_text(
        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
        "tx1,2026-10-10T12:00:00Z,5000,approved,3\n"
        "tx2,2026-10-10T12:00:00Z,5000,approved,missing\n"
    )
    args.update(sales_csv=path, mapping=Path("config/sales_csv.yaml"))
    one, _ = daily_module.daily(conn, "1", **args)
    two, _ = daily_module.daily(conn, "1", **args, now=NOW + timedelta(minutes=1))
    assert one["campaigns"] == two["campaigns"]
    assert two["campaigns"][0]["matched_sales"] == 1 and two["unmatched_sales_bank"] == 1
    assert len(Repository(conn, SaleEvent).list()) == 2
    assert len(Repository(conn, MetricSnapshot).list()) == 2
    assert len(state["requests"]) == 8
    assert len(list(args["output_dir"].iterdir())) == 4


def test_cli_network_failure_preserves_previous_report(daily_case):
    conn, state, args = daily_case
    daily_module.daily(conn, "1", **args)
    before = {p: p.read_bytes() for p in args["output_dir"].iterdir()}
    state["fail"] = True
    result = CliRunner().invoke(
        app,
        [
            "smoke",
            "daily",
            "--campaign",
            "1",
            "--database",
            str(args["database"]),
            "--output-dir",
            str(args["output_dir"]),
            "--json",
        ],
    )
    # Existing minute rejected before HTTP, never overwritten.
    assert result.exit_code == 1 and {p: p.read_bytes() for p in before} == before
    result = CliRunner().invoke(
        app,
        [
            "smoke",
            "daily",
            "--campaign",
            "1",
            "--database",
            str(args["database"]),
            "--output-dir",
            str(args["output_dir"] / "next"),
            "--json",
        ],
    )
    assert result.exit_code == 3 and "Coleta Meta falhou" in result.output
    assert "SYNTHETIC_TOKEN_SENTINEL" not in result.output
    assert not (args["output_dir"] / "next").exists()
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("json_flag,spend,code", [(True, "80.00", 0), (False, "100.00", 2)])
def test_cli_success_and_manual_pause(daily_case, json_flag, spend, code):
    conn, state, args = daily_case
    state["spend"] = spend
    cmd = [
        "smoke",
        "daily",
        "--campaign",
        "1",
        "--database",
        str(args["database"]),
        "--output-dir",
        str(args["output_dir"]),
    ]
    if json_flag:
        cmd.append("--json")
    result = CliRunner().invoke(app, cmd)
    assert result.exit_code == code, result.exception
    if json_flag:
        assert json.loads(result.stdout)["daily"]["exit_code"] == code
    else:
        assert "PAUSE AGORA NO GERENCIADOR" in result.stdout
    assert "SYNTHETIC_TOKEN_SENTINEL" not in result.output


@pytest.mark.parametrize(
    "violation",
    [
        "campaign",
        "naive",
        "since",
        "until",
        "future",
        "csv",
        "mapping",
        "bad_mapping",
        "db_alias",
        "file_dir",
        "config",
        "symlink",
        "hardlink",
    ],
)
def test_invalid_inputs_and_destinations_before_get(daily_case, tmp_path, violation):
    conn, state, args = daily_case
    campaign = "1"
    if violation == "campaign":
        campaign = "bad"
    elif violation == "naive":
        args["now"] = NOW.replace(tzinfo=None)
    elif violation == "since":
        args["since"] = "2026-10-11"
    elif violation == "until":
        args["until"] = "bad"
    elif violation == "future":
        args["until"] = "2026-10-11"
    elif violation == "csv":
        args["sales_csv"] = Path("missing")
    elif violation == "mapping":
        args["mapping"] = Path("config/sales_csv.yaml")
    elif violation == "bad_mapping":
        m = tmp_path / "map.yaml"
        m.write_text("columns: {}")
        args.update(sales_csv=Path("missing"), mapping=m)
    elif violation == "db_alias":
        args["output_dir"] = args["database"]
    elif violation == "file_dir":
        args["output_dir"].write_text("existing report")
    elif violation == "config":
        args["output_dir"] = Path("config")
    elif violation == "symlink":
        link = tmp_path / "link"
        link.symlink_to(args["database"])
        args["output_dir"] = link
    else:
        import os

        args["output_dir"].mkdir()
        os.link(args["database"], args["output_dir"] / "2026-10-10T0900.json")
    before = args["database"].read_bytes()
    with pytest.raises((ValueError, OSError)):
        daily_module.daily(conn, campaign, **args)
    assert not state["requests"] and args["database"].read_bytes() == before


def test_planted_stale_and_two_file_publication_rollback(daily_case, monkeypatch):
    conn, state, args = daily_case
    monkeypatch.setattr(daily_module, "last_collection", lambda _: NOW - timedelta(hours=7))
    original = daily_module.private_open

    def fail_md(path, **kwargs):
        if path.suffix == ".md":
            raise OSError("SYNTHETIC publication failure")
        return original(path, **kwargs)

    monkeypatch.setattr(daily_module, "private_open", fail_md)
    with pytest.raises(OSError):
        daily_module.daily(conn, "1", **args)
    assert list(args["output_dir"].iterdir()) == []
    monkeypatch.setattr(daily_module, "private_open", original)
    value, _ = daily_module.daily(conn, "1", **args)
    assert value["daily"]["stale"] and "AVISO: dado atrasado" in value["daily"]["messages"]
    assert "atrasado" in daily_module.summary(value)


def test_injected_reader_explicit_dates_missing_collection_and_live_guard(daily_case, monkeypatch):
    conn, state, args = daily_case
    monkeypatch.setattr(daily_module, "last_collection", lambda _: None)
    reader = Reader("synthetic", "123", "v99.0")
    value, code = daily_module.daily(
        conn, "1", **args, since="2026-10-10", until="2026-10-10", reader=reader
    )
    assert code == 0 and value["daily"]["collected_at"] is None and value["daily"]["stale"]
    monkeypatch.setenv("LIVE_MODE", "true")  # reader is already attached to MockTransport
    with pytest.raises(ValueError, match="LIVE_MODE"):
        daily_module.daily(conn, "1", **args, reader=reader)


def test_registration_audit_missing_and_unknown_smoke(daily_case):
    from arb.models import Entity

    conn, state, args = daily_case
    with conn:
        original = Repository(conn, Entity).get("meta-1")
        Repository(conn, Entity).add(original.model_copy(update={"id": "meta-9", "meta_id": "9"}))
        conn.execute("INSERT INTO smoke_campaigns VALUES ('meta-9', 11300)")
    with pytest.raises(ValueError, match="auditado"):
        daily_module.daily(conn, "9", **args)
    with pytest.raises(ValueError, match="desconhecida"):
        daily_module.daily(conn, "99", **args)
    assert not state["requests"]


def test_cli_missing_database_refused_without_creation(tmp_path):
    path = tmp_path / "missing.db"
    result = CliRunner().invoke(app, ["smoke", "daily", "--campaign", "1", "--database", str(path)])
    assert result.exit_code == 1 and not path.exists()


def test_report_publication_race_never_removes_preexisting_file(daily_case, monkeypatch):
    conn, state, args = daily_case
    original = daily_module.private_open

    def competing_report(path, **kwargs):
        if path.suffix == ".md":
            path.write_text("SYNTHETIC competing report; preserve")
        return original(path, **kwargs)

    monkeypatch.setattr(daily_module, "private_open", competing_report)
    with pytest.raises(FileExistsError):
        daily_module.daily(conn, "1", **args)
    files = list(args["output_dir"].iterdir())
    assert len(files) == 1 and files[0].suffix == ".md"
    assert files[0].read_text() == "SYNTHETIC competing report; preserve"


def test_graph_version_comes_from_config_when_environment_absent(daily_case, monkeypatch):
    conn, state, args = daily_case
    monkeypatch.delenv("META_API_VERSION")
    args["settings"] = args["settings"].model_copy(update={"meta_api_version": "v99.0"})
    value, _ = daily_module.daily(conn, "1", **args)
    assert value["campaigns"][0]["spend_gross"] == 9040
    assert all("/v99.0/" in r.url.path for r in state["requests"])


@pytest.mark.parametrize("foreign", ["ACTIVE", "PAUSED"])
def test_other_campaign_does_not_break_daily(daily_case, foreign):
    from arb.models import Entity

    conn, state, args = daily_case
    state["foreign"] = foreign
    value, code = daily_module.daily(conn, "1", **args)
    assert code == 0 and value["campaigns"][0]["spend_gross"] == 9040
    assert {e.meta_id for e in Repository(conn, Entity).list()} == {"1", "2", "3"}


@pytest.mark.parametrize("violation", ["ad_campaign", "insight_campaign", "ad_id", "insight_ad"])
def test_campaign_scope_rejects_foreign_or_unregistered_without_report(daily_case, violation):
    conn, state, args = daily_case
    state[violation] = "99"
    before = [s.model_dump() for s in Repository(conn, MetricSnapshot).list()]
    result = CliRunner().invoke(
        app,
        [
            "smoke",
            "daily",
            "--campaign",
            "1",
            "--database",
            str(args["database"]),
            "--output-dir",
            str(args["output_dir"]),
        ],
    )
    assert result.exit_code == 3
    if violation in {"ad_id", "insight_ad"}:
        assert "anúncio novo na fumaça: registre com smoke register" in result.output
    assert not args["output_dir"].exists()
    assert [s.model_dump() for s in Repository(conn, MetricSnapshot).list()] == before


@pytest.mark.parametrize(
    "account,cap,gross,other,code,message",
    [
        ("150.00", None, 16950, 7910, 0, ""),
        ("212.39", 30000, 24000, 14960, 0, "ATENÇÃO: conta perto do spend_cap"),
        ("265.49", 30000, 30000, 20960, 2, "CONTA NO LIMITE: confira o spend_cap no Gerenciador"),
        ("150.00", 30000, 16950, 7910, 0, ""),
    ],
)
def test_account_gross_and_optional_cap_reference(
    daily_case, account, cap, gross, other, code, message
):
    conn, state, args = daily_case
    state["account_spend"] = account
    value, actual = daily_module.daily(conn, "1", **args, account_cap_cents=cap)
    assert (value["daily"]["account_spend_gross"], value["daily"]["other_spend_gross"], actual) == (
        gross,
        other,
        code,
    )
    if message:
        assert message in value["daily"]["messages"]
    text = daily_module.summary(value)
    md = next(args["output_dir"].glob("*.md")).read_text()
    for rendered in (text, md):
        assert f"Gasto da conta na janela: {gross}" in rendered
        assert f"Gasto fora da fumaça: {other}" in rendered


@pytest.mark.parametrize("failure", ["http", "invalid", "inconsistent"])
def test_account_failure_is_informational_without_masking_smoke_limit(daily_case, failure):
    conn, state, args = daily_case
    state["spend"] = "100.00"
    if failure == "http":
        state["account_fail"] = True
    else:
        state["account_spend"] = "bad" if failure == "invalid" else "1.00"
    value, code = daily_module.daily(conn, "1", **args, account_cap_cents=30000)
    assert code == 2
    assert value["daily"]["account_spend_gross"] is None
    assert value["daily"]["other_spend_gross"] is None
    assert "Gasto da conta na janela: indisponível" in daily_module.summary(value)
    assert "PAUSE AGORA NO GERENCIADOR" in value["daily"]["messages"]


def test_account_cap_cli_and_invalid_input_before_get(daily_case):
    conn, state, args = daily_case
    with pytest.raises(ValueError, match="teto de conta"):
        daily_module.daily(conn, "1", **args, account_cap_cents=0)
    assert not state["requests"]
    state["account_spend"] = "265.49"
    result = CliRunner().invoke(
        app,
        [
            "smoke",
            "daily",
            "--campaign",
            "1",
            "--database",
            str(args["database"]),
            "--output-dir",
            str(args["output_dir"]),
            "--account-cap-cents",
            "30000",
            "--json",
        ],
    )
    assert (
        result.exit_code == 2 and json.loads(result.stdout)["daily"]["account_spend_gross"] == 30000
    )


def test_account_subtracts_same_window_not_accumulated_smoke(daily_case):
    conn, state, args = daily_case
    daily_module.daily(conn, "1", **args)
    state["account_spend"] = "150.00"
    value, _ = daily_module.daily(
        conn, "1", **args, since="2026-10-11", until="2026-10-11", now=NOW + timedelta(days=1)
    )
    assert value["campaigns"][0]["spend_gross"] == 18080
    assert value["daily"]["account_spend_gross"] == 16950
    assert value["daily"]["other_spend_gross"] == 7910
