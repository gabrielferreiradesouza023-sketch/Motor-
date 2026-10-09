"""Run every documented arb command against synthetic bank and MockTransport."""

import json
import re
import shlex
from datetime import timedelta
from pathlib import Path
from string import Template

import httpx
import pytest
import yaml
from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect, migrate
from arb.models import MetricSnapshot, Offer

ROOT = Path(__file__).resolve().parents[1]


def setup_bank(path, records):
    connection = connect(path)
    migrate(connection)
    with connection:
        Repository(connection, Offer).add(records[0])
    connection.close()


def test_every_markdown_command_executes_and_matches_pipeline_reference(
    tmp_path, records, monkeypatch
):
    from arb.meta import read
    from arb.sim import calibrate

    bank = tmp_path / "smoke.db"
    setup_bank(bank, records)
    csv = tmp_path / "synthetic-sales.csv"
    csv.write_text(
        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
        + "".join(f"tx{i},2026-10-0{5 + i // 3}T12:00:00Z,5000,approved,3\n" for i in range(9))
    )
    requests = []
    original_init = read.Reader.__init__

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/ads"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "3",
                            "status": "ACTIVE",
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
        if request.url.path.endswith("/insights"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "ad_id": "3",
                            "date_start": f"2026-10-0{day}",
                            "date_stop": f"2026-10-0{day}",
                            "spend": "20.00",
                            "impressions": "2000",
                            "inline_link_clicks": "40",
                            "actions": [{"action_type": "video_view", "value": "600"}],
                        }
                        for day in range(5, 8)
                    ]
                },
            )
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    def reader(self, token, account, version, **kwargs):
        assert token == "synthetic" and account == "123" and version == "v99.0"
        original_init(
            self,
            token,
            account,
            version,
            client=httpx.Client(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(read.Reader, "__init__", reader)
    monkeypatch.setattr(calibrate, "GRID", {"gate_3.min_sales": [2]})
    for name, value in [
        ("LIVE_MODE", "false"),
        ("META_ACCESS_TOKEN", "synthetic"),
        ("META_AD_ACCOUNT_ID", "123"),
        ("META_API_VERSION", "v99.0"),
    ]:
        monkeypatch.setenv(name, value)
    values = dict(
        CAMPANHA="1",
        CONJUNTO="2",
        ANUNCIO="3",
        OFERTA="offer",
        GEO="CO",
        TETO_CENTAVOS="25000",
        BANCO=str(bank),
        DESDE="2026-10-05",
        ATE="2026-10-07",
        CSV=str(csv),
        MAPA_CSV=str(ROOT / "config/sales_csv.yaml"),
        PERFIL=str(tmp_path / "reports/observed.yaml"),
        ROOT=str(ROOT),
        BANCO_LAB=str(tmp_path / "lab.db"),
        FATURA_PLATAFORMA="6000",
        FATURA_TOTAL="6780",
        FATURA_REF="SYNTHETIC invoice only",
    )
    document = (ROOT / "docs/runbooks/piloto.md").read_text()
    commands = [
        line.strip()
        for body in re.findall(r"```sh\n(.*?)```", document, re.S)
        for line in body.splitlines()
        if line.strip()
    ]
    assert len(commands) == 12 and all(line.startswith("uv run arb ") for line in commands)
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    # CLI intentionally loads repo config; provide only public configuration, never .env.
    import shutil

    (tmp_path / "config").mkdir()
    for name in (
        "settings.yaml",
        "rules.yaml",
        "policy.yaml",
        "sim_profiles.yaml",
        "sales_csv.yaml",
    ):
        shutil.copyfile(ROOT / "config" / name, tmp_path / "config" / name)
    outputs = []
    for line in commands:
        arguments = shlex.split(Template(line).substitute(values))[3:]
        result = runner.invoke(app, arguments)
        expected = 1 if arguments[0] in {"preflight", "readiness"} else 0
        assert result.exit_code == expected, (line, result.output, result.exception)
        if expected:
            assert isinstance(result.exception, SystemExit), (line, result.exception)
            assert json.loads(result.output), (line, result.output)
        outputs.append((arguments, result.output))
        if arguments[:2] == ["sync", "meta"]:
            # Synthetic bridge receipts already applied locally, no Worker networking.
            conn = connect(bank)
            with conn:
                Repository(conn, MetricSnapshot).add(
                    records[4].model_copy(
                        update={
                            "entity_id": "meta-3",
                            "ts": records[4].ts + timedelta(hours=1),
                            "impressions": 0,
                            "video_3s_views": 0,
                            "link_clicks": 0,
                            "spend_platform_cents": 0,
                            "bridge_views": 150,
                            "checkout_clicks": 30,
                        }
                    )
                )
            conn.close()
    assert len(requests) == 3 and {r.method for r in requests} == {"GET"}
    smoke = json.loads((tmp_path / "reports/smoke.json").read_text())["campaigns"][0]
    assert (
        smoke["spend_gross"] == 6780
        and smoke["matched_sales"] == 9
        and smoke["implicit_tax_rate"] == pytest.approx(0.13)
    )
    assert (
        smoke["ctr_link"] == 0.02
        and smoke["hook_rate"] == 0.3
        and smoke["bridge_checkout_rate"] == 0.2
    )
    profile = yaml.safe_load(Path(values["PERFIL"]).read_text())["observed_CO"]
    assert profile["winner"]["ctr"][0] < 0.02 < profile["winner"]["ctr"][1]
    assert json.loads((tmp_path / "reports/pilot-calibration.json").read_text())["rows"]
    assert len(json.loads((tmp_path / "reports/pilot-confirmation.json").read_text())["rows"]) == 12
    readiness = json.loads(next(out for args, out in outputs if args[0] == "readiness"))
    assert readiness["ready"] is False and any(not item["ok"] for item in readiness["items"])
    assert (tmp_path / "lab.db").exists()


def test_observed_profile_refuses_source_database_as_output(tmp_path, records):
    bank = tmp_path / "bank.db"
    setup_bank(bank, records)
    before = bank.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "observed",
            "profile",
            "--since",
            "2026-10-05",
            "--until",
            "2026-10-07",
            "--database",
            str(bank),
            "--output",
            str(bank),
        ],
    )
    assert result.exit_code == 2, result.output
    assert bank.read_bytes() == before


@pytest.mark.parametrize(
    "alias",
    [
        "source-json",
        "source-html",
        "same-destinations",
        "hardlink-source-json",
        "hardlink-source-html",
        "symlink-source-json",
        "config-output",
    ],
)
def test_calibration_refuses_overwriting_profile_or_other_output(tmp_path, monkeypatch, alias):
    from arb.sim import calibrate

    monkeypatch.setattr(calibrate, "GRID", {"gate_3.min_sales": [2]})
    source = tmp_path / "synthetic-profile.yaml"
    source.write_text(
        yaml.safe_dump(
            {"planted": yaml.safe_load((ROOT / "config/sim_profiles.yaml").read_text())["planted"]}
        )
    )
    before = source.read_bytes()
    output = source if alias == "source-json" else tmp_path / "out.json"
    report = (
        source
        if alias == "source-html"
        else output
        if alias == "same-destinations"
        else tmp_path / "out.html"
    )
    if alias.startswith("hardlink"):
        import os

        link = tmp_path / "hardlink-output"
        os.link(source, link)
        if alias.endswith("json"):
            output = link
        else:
            report = link
    if alias == "symlink-source-json":
        output = tmp_path / "symlink-output"
        output.symlink_to(source)
    if alias == "config-output":
        output = ROOT / "config" / "pilot-forbidden.json"
    result = CliRunner().invoke(
        app,
        [
            "sim",
            "calibrate",
            "--seeds",
            "1",
            "--workers",
            "1",
            "--profile-file",
            str(source),
            "--output",
            str(output),
            "--report",
            str(report),
        ],
    )
    assert result.exit_code == 2, result.output
    assert source.read_bytes() == before
