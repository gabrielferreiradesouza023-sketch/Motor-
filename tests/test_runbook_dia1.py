"""Execute the operator Markdown, replacing only explicit placeholders with synthetic data."""

import json
import os
import re
import shlex
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from typer.testing import CliRunner

from arb.cli import app
from arb.db import Repository, connect
from arb.launcher import approval
from arb.models import Action, MetricSnapshot

ROOT = Path(__file__).resolve().parents[1]


def commands(document):
    return [
        line.strip()
        for body in re.findall(r"```sh\n(.*?)```", document, re.S)
        for line in body.splitlines()
        if line.strip()
    ]


def test_all_day_one_commands_execute_with_numeric_reference(tmp_path, monkeypatch):
    import arb.readiness as panel
    import arb.smoke as smoke
    import arb.smoke_daily as daily
    import arb.validation as validation
    from arb.db import checkpoint
    from arb.meta.read import Reader

    now = datetime.now(UTC)
    clock = [now]

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    for module in (panel, smoke, daily, validation, checkpoint):
        monkeypatch.setattr(module, "datetime", Frozen)
    monkeypatch.setattr(approval, "is_interactive", lambda: True)
    root = tmp_path / "operator"
    root.mkdir()
    (root / "config").mkdir()
    for name in (
        "settings.yaml",
        "rules.yaml",
        "policy.yaml",
        "sim_profiles.yaml",
        "sales_csv.yaml",
    ):
        shutil.copyfile(ROOT / "config" / name, root / "config" / name)
    shutil.copytree(ROOT / "contracts", root / "contracts")
    (root / "ops").mkdir()
    shutil.copyfile(ROOT / "ops/validation-status.json", root / "ops/validation-status.json")
    csv = tmp_path / "SYNTHETIC-sales.csv"
    csv.write_text(
        "hotmart_tx_id,ts,commission_cents,status,tracking_param\n"
        f"SYNTHETIC_TX,{now.isoformat()},6000,approved,3\n"
    )
    values = {
        "CSV_OFERTAS_COM_PERMISSAO": str(ROOT / "examples/scout/offers-producer.csv"),
        "CSV_OBSERVACOES_ADLIBRARY": str(ROOT / "examples/scout/adlibrary.csv"),
        "CAMINHO_CHAVE_EXISTENTE_NA_ASSINADORA": os.environ["APPROVAL_PRIVATE_KEY_FILE"],
        "REFERENCIA_LIMITE_CARTAO_VERIFICADO": "SYNTHETIC card verification only",
        "REFERENCIA_SPEND_CAP_VERIFICADO": "SYNTHETIC Meta limit verification only",
        "TOKEN_LOCAL_ADS_READ": "SYNTHETIC_ADS_READ_SENTINEL",
        "ID_CONTA_VERIFICADO": "123",
        "VERSAO_GRAPH_VERIFICADA": "v99.0",
        "CAMPANHA": "1",
        "CONJUNTO": "2",
        "ANUNCIO_1": "3",
        "ANUNCIO_2": "4",
        "ANUNCIO_3": "5",
        "OFERTA": "synthetic-producer",
        "GEO_VERIFICADO": "CO",
        "CSV_VENDAS_LOCAL": str(csv),
        "MAPA_VENDAS_VALIDADO": str(ROOT / "config/sales_csv.yaml"),
    }
    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/ads"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": eid,
                            "status": "ACTIVE",
                            "adset": {
                                "id": "2",
                                "status": "ACTIVE",
                                "daily_budget": "1000",
                                "campaign": {"id": "1", "status": "ACTIVE"},
                            },
                        }
                        for eid in ("3", "4", "5")
                    ]
                },
            )
        if request.url.path.endswith("/insights"):
            period = json.loads(request.url.params["time_range"])["since"]
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "ad_id": eid,
                            "date_start": period,
                            "date_stop": period,
                            "impressions": "2000",
                            "spend": "20.00",
                            "inline_link_clicks": "40",
                            "actions": [{"action_type": "video_view", "value": "600"}],
                        }
                        for eid in ("3", "4", "5")
                    ]
                },
            )
        return httpx.Response(200, json={"currency": "BRL", "timezone_name": "America/Sao_Paulo"})

    original = Reader.__init__
    client = httpx.Client(transport=httpx.MockTransport(respond))

    def reader(self, token, account, version, **kwargs):
        assert token == values["TOKEN_LOCAL_ADS_READ"] and version == "v99.0" and account == "123"
        original(self, token, account, version, client=client, attempts=1)

    monkeypatch.setattr(Reader, "__init__", reader)
    monkeypatch.chdir(root)
    doc = (ROOT / "docs/runbooks/dia-1.md").read_text()
    lines = commands(doc)
    assert len(lines) == 18
    assert "LIVE_MODE=true" not in doc
    output = []
    readiness_results = []
    for line in lines:
        rendered = re.sub(r"<([^>]+)>", lambda m: values[m[1]], line)
        assert not re.search(r"<[^>]+>", rendered)
        args = shlex.split(rendered)
        if args[0] == "export":
            assert len(args) == 2
            name, value = args[1].split("=", 1)
            monkeypatch.setenv(name, value)
            continue
        assert args[:3] == ["uv", "run", "arb"], line
        args = args[3:]
        if args[:2] == ["smoke", "daily"]:
            clock[0] += timedelta(minutes=1)
        result = CliRunner().invoke(app, args, input="y\n")
        if args[0] == "readiness":
            info = json.loads(result.stdout)
            readiness_results.append(info)
            expected = 1 if len(readiness_results) == 1 else 0
            assert result.exit_code == expected, (line, result.output, result.exception)
        else:
            assert result.exit_code == 0, (line, result.output, result.exception)
        output.append(result.stdout)
        if args[:2] == ["smoke", "register"]:
            # Already collected synthetic bridge counters; never query a published Worker.
            conn = connect(root / "data/engine.db")
            with conn:
                for eid in ("3", "4", "5"):
                    Repository(conn, MetricSnapshot).add(
                        MetricSnapshot(
                            entity_id="meta-" + eid,
                            ts=now - timedelta(seconds=1),
                            impressions=0,
                            video_3s_views=0,
                            link_clicks=0,
                            spend_platform_cents=0,
                            bridge_views=40,
                            checkout_clicks=1,
                        )
                    )
            conn.close()
    assert not readiness_results[0]["ready"]
    assert {r["item"] for r in readiness_results[0]["pending"]} == {
        "smoke_registered",
        "smoke_offer_permission",
    }
    assert readiness_results[1]["ready"]
    assert len(requests) == 6 and {r.method for r in requests} == {"GET"}
    reports = sorted((root / "reports/smoke").glob("*.json"))
    assert len(reports) == 2
    data = json.loads(reports[-1].read_text())
    row = data["campaigns"][0]
    assert row["spend_platform_cents"] == 6000 and row["spend_gross"] == 6780
    assert row["impressions"] == 6000 and row["cpm_gross"] == 1130
    assert row["ctr_link"] == 0.02 and row["hook_rate"] == 0.3
    assert row["bridge_views"] == 120 and row["checkout_clicks"] == 3 and row["matched_sales"] == 1
    conn = connect(root / "data/engine.db")
    assert not {a.kind for a in Repository(conn, Action).list()} & {
        "activate",
        "pause",
        "scale",
        "launch",
    }
    result = CliRunner().invoke(app, ["readiness", "--json"])
    assert result.exit_code == 1 and not json.loads(result.stdout)["ready"]
    assert "SYNTHETIC_ADS_READ_SENTINEL" not in "\n".join(output)
    # Optional local evidence export used by the batch report; only public configs,
    # signed synthetic records and a consistent SQLite backup, never a private key.
    if destination := os.environ.get("ARB_TEST_EVIDENCE_ROOT"):
        dest = Path(destination)
        dest.mkdir()
        shutil.copytree(root / "config", dest / "config")
        shutil.copytree(root / "contracts", dest / "contracts")
        shutil.copytree(root / "ops", dest / "ops")
        (dest / "data/backups").mkdir(parents=True)
        target = connect(dest / "data/engine.db")
        conn.backup(target)
        target.close()
        shutil.copy2(root / "data/backups/drill.json", dest / "data/backups/drill.json")
    conn.close()
    client.close()


def test_every_placeholder_has_a_named_human_input():
    doc = (ROOT / "docs/runbooks/dia-1.md").read_text()
    placeholders = set(re.findall(r"<([^>]+)>", "\n".join(commands(doc))))
    assert placeholders == {
        "CSV_OFERTAS_COM_PERMISSAO",
        "CSV_OBSERVACOES_ADLIBRARY",
        "CAMINHO_CHAVE_EXISTENTE_NA_ASSINADORA",
        "REFERENCIA_LIMITE_CARTAO_VERIFICADO",
        "REFERENCIA_SPEND_CAP_VERIFICADO",
        "TOKEN_LOCAL_ADS_READ",
        "ID_CONTA_VERIFICADO",
        "VERSAO_GRAPH_VERIFICADA",
        "CAMPANHA",
        "CONJUNTO",
        "ANUNCIO_1",
        "ANUNCIO_2",
        "ANUNCIO_3",
        "OFERTA",
        "GEO_VERIFICADO",
        "CSV_VENDAS_LOCAL",
        "MAPA_VENDAS_VALIDADO",
    }
    assert "### O que o humano precisa fazer" in doc
