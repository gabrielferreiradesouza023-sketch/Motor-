"""Sensibilidade em memória. JSON determinístico; nenhum arquivo de regra é escrito."""

import itertools
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
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


CONFIRMATION_VARIANTS = {"current": None, "C-10000": 10000, "C-15000": 15000, "C-20000": 20000}


def confirmation_variant(base: Rules, name: str) -> Rules:
    from arb.config import GateC

    if name not in CONFIRMATION_VARIANTS:
        raise ValueError("variante de confirmação inválida")
    cap = CONFIRMATION_VARIANTS[name]
    return base.model_copy(
        update={
            "gate_C": None
            if cap is None
            else GateC(cap_cents=cap, min_sales_total=4, min_roi=0, min_p_roi_positive=0.8)
        }
    )


def confirm_report(
    *,
    seeds=None,
    profiles=("planted", "realistic", "pessimistic"),
    variants=tuple(CONFIRMATION_VARIANTS),
    workers: int = 1,
) -> dict:
    from arb.sim.lab import confirmation_stats

    seeds = list(range(100)) if seeds is None else seeds
    if not seeds or len(set(seeds)) != len(seeds) or any(type(s) is not int for s in seeds):
        raise ValueError("seeds inteiras únicas são obrigatórias")
    if not profiles or any(p not in {"planted", "realistic", "pessimistic"} for p in profiles):
        raise ValueError("perfil inválido")
    if not variants or len(set(variants)) != len(variants):
        raise ValueError("variantes únicas obrigatórias")
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers precisa estar em 1–8")
    base = load_rules()
    rows = []
    with ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext() as pool:
        for profile in profiles:
            for name in variants:
                r = confirmation_variant(base, name)
                runs = (
                    list(
                        pool.map(
                            _confirmation_seed, [(seed, profile, r.model_dump()) for seed in seeds]
                        )
                    )
                    if pool
                    else [
                        confirmation_stats(run_lab(seed, profile=profile, rules=r))
                        for seed in seeds
                    ]
                )
                totals = {
                    key: sum(run[key] for run in runs)
                    for key in (
                        "true_winners",
                        "true_losers",
                        "true_validations",
                        "false_validations",
                        "missed_winners",
                        "spend_gross_cents",
                    )
                }
                rows.append(
                    {
                        "profile": profile,
                        "variant": name,
                        "seeds": len(seeds),
                        **totals,
                        "false_positive_rate": totals["false_validations"] / totals["true_losers"]
                        if totals["true_losers"]
                        else None,
                        "winner_hit_rate": totals["true_validations"] / totals["true_winners"]
                        if totals["true_winners"]
                        else None,
                        "mean_total_spend_cents": totals["spend_gross_cents"] / len(seeds),
                        "spend_per_true_winner_cents": totals["spend_gross_cents"]
                        / totals["true_validations"]
                        if totals["true_validations"]
                        else None,
                    }
                )
    return {
        "seeds": seeds,
        "hypotheses_not_market_data": True,
        "truth_definition": (
            "expected net revenue > gross media cost; equal impressions per creative"
        ),
        "confirmation": {"min_sales_total": 4, "min_roi": 0, "min_p_roi_positive": 0.8},
        "rows": rows,
        "limitations": [
            "Perfis são hipóteses, não dados de mercado. Não escolher "
            "configuração automaticamente.",
            "Taxa FP = perdedores validados / perdedores verdadeiros; acerto "
            "= vencedores validados / vencedores verdadeiros.",
            "Custo por vencedor inclui todo gasto e divide somente pelos "
            "vencedores verdadeiros validados; sem acerto é null.",
            "Taxas do perfil são amostradas uma vez; C usa novos lotes no "
            "mesmo geo e métricas acumuladas.",
            "Avaliações repetidas, seleção nos portões anteriores e 100 seeds "
            "não garantem taxa fora da amostra.",
            "Sem C, saídas históricas de summary/calibrate permanecem inalteradas.",
        ],
    }


def confirmation_markdown(result: dict) -> str:
    def number(value, rate=False):
        return "—" if value is None else f"{value * 100:.2f}%" if rate else f"{value:.2f}"

    lines = [
        "# Confirmação estatística — hipóteses, não mercado",
        "",
        f"Seeds: {len(result['seeds'])}. Valores monetários em centavos. "
        "C desligado nas regras atuais.",
        "",
        "| Perfil | Variante | FP / perdedores | Taxa FP | Acertos / "
        "vencedores | Acerto | Gasto médio | Gasto por vencedor |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in result["rows"]:
        lines.append(
            f"| {r['profile']} | {r['variant']} | {r['false_validations']} / {r['true_losers']} | "
            f"{number(r['false_positive_rate'], True)} | "
            f"{r['true_validations']} / {r['true_winners']} | "
            f"{number(r['winner_hit_rate'], True)} | {number(r['mean_total_spend_cents'])} | "
            f"{number(r['spend_per_true_winner_cents'])} |"
        )
    return "\n".join(lines + ["", *["- " + item for item in result["limitations"]], ""])


def _confirmation_seed(task):
    from arb.sim.lab import confirmation_stats

    seed, profile, rules = task
    return confirmation_stats(run_lab(seed, profile=profile, rules=Rules.model_validate(rules)))
