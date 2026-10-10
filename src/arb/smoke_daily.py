"""Daily human smoke observation: GET collection, local imports, exclusive reports."""

import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from arb.config import Settings, load_sales_csv
from arb.db import Repository
from arb.launcher.execute import require_simulation
from arb.meta.read import Reader
from arb.meta.sync import last_collection, sync
from arb.models import Action
from arb.permissions import private_open, report_paths
from arb.smoke import markdown, report
from arb.tracker import import_sales

PREPARE_FRACTION = Decimal("0.8")


def daily(
    connection,
    campaign,
    *,
    settings: Settings,
    rules,
    database: Path,
    output_dir=Path("reports/smoke"),
    since=None,
    until=None,
    sales_csv=None,
    mapping=None,
    reader=None,
    now=None,
):
    require_simulation()
    now = now or datetime.now(UTC)
    if now.utcoffset() is None or not re.fullmatch(r"[0-9]+", campaign):
        raise ValueError("campanha/data inválida")
    zone = ZoneInfo(settings.timezone)
    local = now.astimezone(zone)
    identifier = "meta-" + campaign
    report(connection, identifier, media_tax_rate=settings.media_tax_rate)  # refuse unknown smoke
    registrations = [
        a.ts
        for a in Repository(connection, Action).list()
        if a.kind == "smoke_register"
        and a.actor == "human"
        and a.payload_json.get("campaign") == campaign
    ]
    if not registrations:
        raise ValueError("registro auditado da fumaça ausente")
    since = (
        date.fromisoformat(since)
        if since is not None
        else min(registrations).astimezone(zone).date()
    )
    until = date.fromisoformat(until) if until is not None else local.date()
    if since > until or until > local.date():
        raise ValueError("janela de coleta inválida")
    if bool(sales_csv) != bool(mapping):
        raise ValueError("CSV de vendas exige --mapping explícito e validado")
    sales_map = load_sales_csv(Path(mapping)) if mapping else None
    targets = [
        output_dir / (local.strftime("%Y-%m-%dT%H%M") + suffix) for suffix in (".json", ".md")
    ]
    report_paths([output_dir], source=database)
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("saída exige diretório")
    report_paths(targets, source=database)
    if any(target.exists() for target in targets):
        raise ValueError("relatório já existe; escolher outra coleta/minuto ou diretório")
    owned = reader is None
    if owned:
        reader = Reader(
            os.environ.get("META_ACCESS_TOKEN", ""),
            os.environ.get("META_AD_ACCOUNT_ID", ""),
            os.environ.get("META_API_VERSION") or settings.meta_api_version or "",
        )
    try:
        sync(connection, reader, since, until, now=now)
    finally:
        if owned:
            reader.close()
    if sales_csv:
        import_sales(connection, Path(sales_csv), mapping=sales_map)
    value = report(connection, identifier, media_tax_rate=settings.media_tax_rate)
    row = value["campaigns"][0]
    gross, cap = row["spend_gross"], row["cap_cents"]
    stamp = last_collection(connection)
    stale = stamp is None or now - stamp > timedelta(hours=rules.controls.stale_after_hours)
    code = 2 if gross >= cap or row["alerts"] else 0
    alert = (
        "PAUSE AGORA NO GERENCIADOR"
        if code == 2
        else ("ATENÇÃO: prepare-se para pausar" if gross >= cap * PREPARE_FRACTION else "")
    )
    messages = [m for m in (alert, "AVISO: dado atrasado" if stale else "") if m]
    value["daily"] = {
        "collected_at": stamp.isoformat() if stamp else None,
        "local_time": local.isoformat(),
        "since": since.isoformat(),
        "until": until.isoformat(),
        "stale": stale,
        "cap_percent": gross * 100 / cap,
        "exit_code": code,
        "messages": messages,
    }
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    md = markdown(value) + "\n" + "\n".join(messages) + "\n"
    created = []
    try:
        for target, content in zip(targets, (text, md), strict=True):
            with private_open(target, exclusive=True) as stream:
                created.append(target)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for target in created:
            target.unlink()
        raise
    return value, code


def summary(value):
    row = value["campaigns"][0]
    state = value["daily"]
    return "\n".join(
        [
            f"Gasto bruto estimado: {row['spend_gross']} centavos "
            f"({state['cap_percent']:.2f}% do teto)",
            f"CPM bruto: {row['cpm_gross']}; CTR: {row['ctr_link']}; hook: {row['hook_rate']}",
            f"Visitas à ponte: {row['bridge_views']}; checkouts: {row['checkout_clicks']}",
            f"Vendas casadas: {row['matched_sales']}; "
            f"não casadas (banco inteiro): {value['unmatched_sales_bank']}",
            f"Última coleta: {state['collected_at']}; "
            f"dado {'atrasado' if state['stale'] else 'recente'}",
            *state["messages"],
        ]
    )
