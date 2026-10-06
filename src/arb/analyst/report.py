"""Relatório HTML responsivo e escapado. Sem scripts ou links de ativação."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, select_autoescape

from arb.analyst import pnl

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
<p class="decision-question">{{ question }}</p><footer>Revisar aprovações por arquivo.
Nenhuma decisão neste relatório ativa ou aumenta exposição.</footer></main></body></html>"""


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
    stamp = (now or datetime.now(UTC)).astimezone(ZoneInfo("America/Sao_Paulo"))
    environment = Environment(autoescape=select_autoescape(default_for_string=True))
    environment.filters["money"] = lambda v: "—" if v is None else f"R$ {v / 100:,.2f}"
    environment.filters["percent"] = lambda v: "—" if v is None else f"{v * 100:.1f}%"
    pending = sorted(approval_dir.glob("*.json"))
    question = (
        f"Aprovar ou rejeitar o plano pendente {pending[0].name}?"
        if pending
        else "Manter a simulação até a próxima revisão?"
    )
    terminal = [
        d
        for d in sorted(data["decisions"], key=lambda d: d["ts"])
        if d["verdict"] in ("pass", "kill")
    ][-12:]
    rendered = environment.from_string(TEMPLATE).render(
        t=data["totals"],
        stamp=stamp.strftime("%d/%m/%Y %H:%M"),
        decisions=terminal,
        offers=data["groups"]["offer"],
        alerts=data["alerts"],
        unmatched=len(data["unmatched"]),
        question=question,
    )
    output.mkdir(parents=True, exist_ok=True)
    dated = output / f"{stamp.strftime('%Y-%m-%d_%H%M%S')}.html"
    dated.write_text(rendered)
    temporary = output / ".latest.tmp"
    temporary.write_text(rendered)
    temporary.replace(output / "latest.html")
    return output / "latest.html"
