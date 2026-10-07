"""Relatório HTML responsivo e escapado. Sem scripts ou links de ativação."""

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, select_autoescape

from arb.analyst import pnl
from arb.analyst.decisions import question as decision_question
from arb.analyst.decisions import queue
from arb.db import Repository
from arb.ledger import pending as ledger_pending
from arb.models import Approval
from arb.permissions import private_directory, private_open
from arb.quarantine import current

TEMPLATE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>arb-engine · Relatório diário</title><style>
body{font:16px system-ui;margin:0;background:#f4f5f7;color:#172033}
main{max-width:900px;margin:auto;padding:16px}h1{font-size:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.card,section{background:white;padding:16px;border-radius:12px;margin-bottom:12px}
strong{display:block;font-size:24px}small{color:#4e5868}ul{padding-left:20px}
.row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
border-bottom:1px solid #ddd;padding:8px 0}
.decision-question{background:#153c56;color:white;padding:16px;border-radius:12px}
.badge{font-size:12px}footer{font-size:13px}</style></head><body><main>
<h1>arb-engine · {{ stamp }}</h1><p>SIMULAÇÃO · Receita esperada, não disponível para reciclar.</p>
<div class="cards"><div class="card">Gasto bruto<strong>{{ t.spend_gross|money }}</strong></div>
<div class="card">Receita esperada<strong>{{ t.rev_expected|money }}</strong></div>
<div class="card">P&amp;L<strong>{{ t.profit_cents|money }}</strong></div>
<div class="card">Caixa restante<strong>{{ t.cash_remaining_cents|money }}</strong></div></div>
<section><h2>Estado operacional</h2><ul>
<li>Ledger: {{ ops.pending }} pendências; {{ ops.uncertain }} incertas;
{{ ops.orphans }} órfãs. Consultar arb ops pending para detalhes.</li>
<li>Alertas incertos sem ack: {{ ops.unacked_alerts|length }}. Consultar arb ops alerts.</li>
{% for row in ops.unacked_alerts %}<li>{{ row.id }} · {{ row.codes|join(', ') }}
· {{ 'freio/stale requer ack' if row.critical else 'revisar' }}</li>{% endfor %}
<li>Resultados incertos no histórico: {{ ops.uncertain_results }}</li>
<li>Quarentena: {{ 'aberta' if ops.quarantine else 'nenhuma' }}</li>
<li>Idade do último backup (s): {{ ops.backup_age_seconds if
ops.backup_age_seconds is not none else 'ausente' }}</li>
<li>Último drill: {{ 'verde' if ops.drill.status == 'passed' else 'falho ou ausente' }};
idade (s): {{ ops.drill.age_seconds if ops.drill.age_seconds is not none else 'desconhecida' }}</li>
<li>Última reconciliação: {{ ops.last_reconciliation or 'ausente' }}</li></ul>
<p>Aprovações pendentes por tipo (banco):</p><ul>
{% for kind, count in ops.pending_approvals.items() %}
<li>{{ kind }}: {{ count }}</li>{% else %}<li>Nenhuma.</li>{% endfor %}</ul></section>
<section><h2>Aprendizado</h2><p>Desperdício: {{ t.waste_ratio|percent }} · Custo por aprendizado:
{{ t.cost_per_learning_cents|money }}</p></section>
<section><h2>Mortos e promovidos</h2><ul>{% for d in decisions %}<li>
{{ d.entity_id }} · {{ d.verdict }} · {{ d.reason }}</li>
{% else %}<li>Sem vereditos.</li>{% endfor %}</ul></section>
<section><h2>Ofertas</h2>{% for row in offers %}<div class="row"><span>{{ row.key }}
{% if row.reopened %}<span class="badge">Reopened · revisar sem reativar</span>{% endif %}</span>
<span>{{ row.profit_cents|money }} · ROI {{ row.roi_expected|percent }}</span></div>
{% endfor %}</section>
<section><h2>Alertas</h2><ul>{% for alert in alerts %}<li>{{ alert }}</li>{% endfor %}
{% if unmatched %}<li>{{ unmatched }} vendas sem casamento.</li>{% endif %}</ul></section>
<section><h2>Fila de decisões humanas</h2><p>Arquivos válidos pendentes por tipo:</p>
<ul>{% for kind, count in queue_counts.items() %}<li>{{ kind }}: {{ count }}</li>
{% else %}<li>Nenhuma.</li>{% endfor %}</ul><ul>{% for row in human_queue['items'] %}
<li>{{ row.kind }} · {{ row.summary }} · Exposição {{ row.max_exposure_cents|money }}
· Idade {{ row.age_seconds }} s · Hash {{ row.plan_hash_short }}
<br><code>{{ row.command }}</code><br><small>{{ row.expiry_suggestion }}</small></li>
{% else %}<li>Nenhuma proposta válida pendente.</li>{% endfor %}</ul>
{% if human_queue.invalid %}<p>{{ human_queue.invalid }} arquivos inválidos exigem revisão.</p>
{% endif %}<p>Idade baseada no mtime; informativa, sem validade automática.</p></section>
<p class="decision-question">{{ question }}</p><footer>Revisar aprovações por arquivo.
Nenhuma decisão neste relatório ativa ou aumenta exposição.</footer></main></body></html>"""


def _drill_status(directory, now):
    failed = {"status": "failed", "age_seconds": None}
    if directory is None:
        return failed
    try:
        path = directory / "drill.json"
        if path.is_symlink():
            raise ValueError("drill não pode ser symlink")
        body = json.loads(path.read_text())
        stamp = datetime.fromisoformat(body["checked_at"])
        age = (now - stamp).total_seconds()
        name = body["backup"]
        if (
            body["status"] != "passed"
            or body["quarantined"] is not True
            or age < 0
            or not isinstance(name, str)
            or not re.fullmatch(
                r"(?:engine-[0-9-]+|pre-(?:launch|activate|scale)-[A-Za-z0-9_-]+)\.db", name
            )
        ):
            raise ValueError("evidência de drill inválida")
        source = directory / name
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != body["sha256"]:
            raise ValueError("backup diverge da evidência")
        return {"status": "passed", "age_seconds": int(age)}
    except (OSError, ValueError, KeyError, TypeError):
        return failed


def operational_status(connection, *, now=None):
    now = now or datetime.now(UTC)
    from arb.scheduler.alerts import uncertain

    rows = ledger_pending(connection, now=now)
    reconciled = [
        datetime.fromisoformat(row[0])
        for row in connection.execute(
            "SELECT action_ts FROM actions WHERE action_result GLOB 'reconciled_*'"
        )
    ]
    uncertain_count = connection.execute(
        "SELECT count(*) FROM actions WHERE action_result='uncertain'"
    ).fetchone()[0]
    approvals = Counter(
        a.kind for a in Repository(connection, Approval).list() if a.status == "pending"
    )
    database = connection.execute("PRAGMA database_list").fetchone()[2]
    directory = Path(database).parent / "backups" if database else None
    age = None
    if directory is not None:
        try:
            files = [p for p in directory.glob("*.db") if p.is_file() and not p.is_symlink()]
            if files:
                latest = max(p.stat().st_mtime for p in files)
                age = max(0, int(now.timestamp() - latest))
        except OSError:
            pass
    return {
        "unacked_alerts": uncertain(connection),
        "pending": len(rows),
        "uncertain": sum(row["state"] == "uncertain" for row in rows),
        "orphans": sum(row["state"] == "orphan" for row in rows),
        "uncertain_results": uncertain_count,
        "quarantine": current(connection) is not None,
        "backup_age_seconds": age,
        "drill": _drill_status(directory, now),
        "last_reconciliation": max(reconciled).isoformat() if reconciled else None,
        "pending_approvals": dict(sorted(approvals.items())),
    }


def generate_report(
    connection: sqlite3.Connection,
    output: Path = Path("reports"),
    *,
    approval_dir: Path = Path("ops/approvals/pending"),
    now: datetime | None = None,
    alert_messages: list[str] | None = None,
) -> Path:
    data = pnl(connection)
    data["alerts"].extend(alert_messages or [])
    instant = now or datetime.now(UTC)
    stamp = instant.astimezone(ZoneInfo("America/Sao_Paulo"))
    environment = Environment(autoescape=select_autoescape(default_for_string=True))
    environment.filters["money"] = lambda v: "—" if v is None else f"R$ {v / 100:,.2f}"
    environment.filters["percent"] = lambda v: "—" if v is None else f"{v * 100:.1f}%"
    human_queue = queue(approval_dir, now=instant)
    question = decision_question(human_queue)
    terminal = [
        d
        for d in sorted(data["decisions"], key=lambda d: d["ts"])
        if d["verdict"] in ("pass", "kill")
    ][-12:]
    rendered = environment.from_string(TEMPLATE).render(
        t=data["totals"],
        ops=operational_status(connection, now=instant),
        stamp=stamp.strftime("%d/%m/%Y %H:%M"),
        decisions=terminal,
        offers=data["groups"]["offer"],
        alerts=data["alerts"],
        unmatched=len(data["unmatched"]),
        question=question,
        human_queue=human_queue,
        queue_counts=Counter(row["kind"] for row in human_queue["items"]),
    )
    private_directory(output)
    dated = output / f"{stamp.strftime('%Y-%m-%d_%H%M%S')}.html"
    with private_open(dated) as file:
        file.write(rendered)
    temporary = output / ".latest.tmp"
    with private_open(temporary) as file:
        file.write(rendered)
    temporary.replace(output / "latest.html")
    return output / "latest.html"
