"""Sensibilidade em memória. JSON determinístico; nenhum arquivo de regra é escrito."""

import itertools
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from jinja2 import Environment

from arb.config import Rules
from arb.rules import load_rules
from arb.sim.lab import run_lab

GRID = {
    "gate_3.min_sales": [1, 2, 3],
    "gate_3.commission_cap_multiplier": [2, 3, 4],
    "gate_3.hard_cap_multiplier": [1.25, 1.5, 2.0],
    "gate_1.kill_ctr_link": [0.006, 0.008, 0.010],
}


def variant(base: Rules, parameters: dict) -> Rules:
    values = base.model_dump()
    for key, value in parameters.items():
        if key not in GRID:
            raise ValueError("parâmetro fora do grid permitido")
        section, field = key.split(".")
        values[section][field] = value
    return Rules.model_validate(values)


def _cell(task):
    index, profile, parameters, seeds, rules, current = task
    rules = Rules.model_validate(rules)
    runs = [run_lab(seed, profile=profile, rules=rules).summary() for seed in seeds]
    validated = [
        r["spend_to_first_g3_pass_cents"]
        for r in runs
        if r["spend_to_first_g3_pass_cents"] is not None
    ]
    return dict(
        id=f"cell-{index:03d}-{profile}",
        profile=profile,
        parameters=parameters,
        seeds=len(seeds),
        winner_found_rate=sum(r["winner_found"] for r in runs) / len(runs),
        borderline_found_rate=sum(r["borderline_found"] for r in runs) / len(runs),
        killed_winner_rate=sum(bool(r["killed_winners"]) for r in runs) / len(runs),
        mean_waste_ratio=sum(r["waste_ratio"] or 0 for r in runs) / len(runs),
        mean_spend_to_validate_cents=sum(validated) / len(validated) if validated else None,
        validations=len(validated),
        mean_total_spend_cents=sum(r["spend_gross_cents"] for r in runs) / len(runs),
        current=parameters == current,
    )


def calibrate(
    *,
    grid: dict | None = None,
    seeds: list[int] | None = None,
    profiles: tuple[str, ...] = ("realistic", "pessimistic"),
    workers: int = 1,
) -> dict:
    grid = GRID if grid is None else grid
    seeds = list(range(100)) if seeds is None else seeds
    if not seeds or len(set(seeds)) != len(seeds) or any(type(s) is not int for s in seeds):
        raise ValueError("seeds inteiras únicas são obrigatórias")
    if not grid or any(k not in GRID or not v for k, v in grid.items()):
        raise ValueError("grid inválido")
    if not profiles or any(p not in {"realistic", "pessimistic"} for p in profiles):
        raise ValueError("perfil inválido")
    if workers < 1 or workers > 8:
        raise ValueError("workers precisa estar em 1–8")
    base = load_rules()
    current = {k: getattr(getattr(base, k.split(".")[0]), k.split(".")[1]) for k in GRID}
    keys = sorted(grid)
    tasks = []
    for index, values in enumerate(itertools.product(*(grid[k] for k in keys))):
        parameters = current | dict(zip(keys, values, strict=True))
        rules = variant(base, parameters)
        tasks.extend((index, p, parameters, seeds, rules.model_dump(), current) for p in profiles)
    if workers == 1:
        rows = [_cell(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_cell, tasks))
    for row in rows:
        row["pareto"] = not any(
            other["profile"] == row["profile"]
            and other["winner_found_rate"] >= row["winner_found_rate"]
            and other["mean_waste_ratio"] <= row["mean_waste_ratio"]
            and (
                other["winner_found_rate"] > row["winner_found_rate"]
                or other["mean_waste_ratio"] < row["mean_waste_ratio"]
            )
            for other in rows
        )
    return {
        "seeds": seeds,
        "profiles": list(profiles),
        "hypotheses_not_market_data": True,
        "current_parameters": current,
        "rows": rows,
        "limitations": [
            "Média até validar é condicionada ao sucesso; não é custo garantido.",
            "O simulador pausa G3 no teto nominal para revisão; "
            "hard_cap não autoriza gastar além dele.",
            "Receita esperada não é reciclada; distribuições são hipóteses independentes.",
        ],
    }


def html_report(result: dict, output: Path) -> Path:
    template = """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Calibração diagnóstica</title><style>body{font:15px system-ui;margin:24px}
table{border-collapse:collapse}th,td{padding:8px;border:1px solid #ddd}
.current{background:#ddf1ff}.pareto{font-weight:bold}th{cursor:pointer}</style>
<h1>Hipóteses, sem alteração de rules.yaml</h1>
<p>Azul: célula atual. Negrito: fronteira de Pareto (acerto × waste). Clique no cabeçalho.</p>
<ul>{% for limit in limitations %}<li>{{limit}}</li>{% endfor %}</ul>
<table><thead><tr>{% for name in columns %}<th>{{name}}</th>{% endfor %}</tr></thead><tbody>
{% for row in rows %}<tr class="{% if row.current %}current {% endif %}
{% if row.pareto %}pareto{% endif %}">
<td>{{row.id}}</td><td>{{row.parameters}}</td><td>{{row.winner_found_rate}}</td>
<td>{{row.borderline_found_rate}}</td><td>{{row.mean_waste_ratio}}</td>
<td>{{row.mean_spend_to_validate_cents}}</td><td>{{row.mean_total_spend_cents}}</td></tr>
{% endfor %}
</tbody></table><script>
document.querySelectorAll('th').forEach((th,i)=>th.onclick=()=>{
 const body=document.querySelector('tbody');const rows=[...body.rows];
 const direction=th.dataset.direction==='up'?-1:1;th.dataset.direction=direction===1?'up':'down';
 rows.sort((a,b)=>{const x=a.cells[i].textContent,y=b.cells[i].textContent;
 return direction*(!isNaN(+x)&&!isNaN(+y)?+x-+y:x.localeCompare(y));});
 rows.forEach(r=>body.appendChild(r));});</script></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        Environment(autoescape=True)
        .from_string(template)
        .render(
            **result,
            columns=[
                "Célula",
                "Parâmetros",
                "Acerto",
                "Borderline",
                "Waste",
                "Até validar (centavos)",
                "Total (centavos)",
            ],
        )
    )
    return output
