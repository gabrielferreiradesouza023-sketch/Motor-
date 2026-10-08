"""Laboratório completo, determinístico por seed, sem conexão com APIs."""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arb.config import Rules
from arb.db import Repository, connect, migrate
from arb.metrics import cost_per_learning, rev_expected, spend_gross, waste_ratio
from arb.models import Decision, MetricSnapshot, SaleEvent
from arb.rules import controls, evaluate, load_rules
from arb.sim import Population, aggregate, population, traffic


@dataclass
class Run:
    seed: int
    population: Population
    snapshots: list[MetricSnapshot] = field(default_factory=list)
    sales: list[SaleEvent] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    winners: list[str] = field(default_factory=list)
    killed_winners: list[str] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    excess_cents: int = 0
    profile: str = "planted"

    def summary(self) -> dict:
        gross = spend_gross(sum(s.spend_platform_cents for s in self.snapshots))
        sampled = sum(
            d.verdict in ("pass", "kill") and d.metrics_json["sample_sufficient"]
            for d in self.decisions
        )
        truth_winners = {
            c.angle_id for c in self.population.creatives if self.population.truth[c.id].winner
        }
        borderline = {
            c.angle_id
            for c in self.population.creatives
            if self.population.truth[c.id].role == "borderline_winner"
        }
        deaths = [
            dict(entity_id=d.entity_id, gate=d.gate, rule_id=d.rule_id)
            for d in self.decisions
            if d.verdict == "kill"
            and any(
                e.id == d.entity_id and e.angle_id in truth_winners
                for e in self.population.entities
            )
        ]
        first_pass = next(
            (d.ts for d in self.decisions if d.gate == "3" and d.verdict == "pass"), None
        )
        return {
            "profile": self.profile,
            "winner_found": bool(truth_winners & set(self.winners)),
            "borderline_found": bool(borderline & set(self.winners)),
            "winner_deaths": deaths,
            "spend_to_first_g3_pass_cents": spend_gross(
                sum(
                    s.spend_platform_cents
                    for s in self.snapshots
                    if first_pass and s.ts <= first_pass
                )
            )
            if first_pass
            else None,
            "seed": self.seed,
            "spend_gross_cents": gross,
            "revenue_expected_cents": rev_expected(self.sales),
            "winners": self.winners,
            "killed_winners": self.killed_winners,
            "planted_found": "o0-a0" in self.winners,
            "waste_ratio": waste_ratio(self.excess_cents, gross),
            "cost_per_learning_cents": cost_per_learning(gross, sampled),
            "sampled_verdicts": sampled,
            "alerts": self.alerts,
        }


def run_lab(
    seed: int, budget_cents: int = 240000, *, profile: str = "planted", rules: Rules | None = None
) -> Run:
    if budget_cents <= 0:
        raise ValueError("orçamento precisa ser positivo")
    r = Rules.model_validate(rules.model_dump()) if rules else load_rules()
    budget_cents = min(budget_cents, r.controls.total_cap_cents)
    p = population(seed, profile=profile)
    run = Run(seed, p, profile=profile)
    rng = random.Random(seed)
    ads = [e for e in p.entities if e.kind == "ad"]
    groups = {e.angle_id: e for e in p.entities if e.kind == "adset"}
    states = {e.id: "testing" for e in ads}
    stages = {a: "1" for a in groups}
    histories = {e.id: [] for e in ads}
    confirmation_starts = {}
    platform_total = 0
    day_platform = 0
    day_sales = []
    day = 0
    step = 0
    stopped = False
    while any(stage in ("1", "2", "3", "C") for stage in stages.values()) and not stopped:
        step += 1
        if step > 10000:
            raise RuntimeError("simulação não convergiu")
        now = datetime(2026, 10, 5, 12, tzinfo=UTC) + timedelta(days=day, seconds=step)
        for ad in ads:
            stage = stages[ad.angle_id]
            eligible = states[ad.id] == "testing" if stage == "1" else states[ad.id] == "pass"
            if stage not in ("1", "2", "3", "C") or not eligible:
                continue
            # Estima conservadoramente o custo máximo do lote antes de entregar.
            max_platform = round(p.truth[ad.id].cpm_cents * 0.115)
            projected = spend_gross(platform_total + max_platform)
            if projected > budget_cents:
                stopped = True
                run.alerts.append("budget: saldo insuficiente para próximo lote")
                break
            snap, sales = traffic(ad, p.truth[ad.id], rng, now)
            histories[ad.id].append(snap)
            run.snapshots.append(snap)
            run.sales.extend(sales)
            day_sales.extend(sales)
            platform_total += snap.spend_platform_cents
            day_platform += snap.spend_platform_cents
            if stage == "1":
                total = aggregate(histories[ad.id], ad.id, now)
                own_sales = [s for s in run.sales if s.matched_entity_id == ad.id]
                decision = evaluate(ad, total, own_sales, 6000, r, now)
                decision.id = f"s{seed}-d{len(run.decisions)}"
                run.decisions.append(decision)
                if decision.verdict in ("kill", "pass"):
                    states[ad.id] = decision.verdict
                    if decision.verdict == "kill":
                        ad.status = "paused"
                        run.excess_cents += max(
                            0,
                            decision.metrics_json["spend_gross"]
                            - decision.metrics_json["cap_cents"],
                        )
            alerts = controls(
                r,
                day_spend_cents=spend_gross(day_platform),
                day_revenue_cents=rev_expected(day_sales),
                total_spend_cents=spend_gross(platform_total),
                passed_gate_2=sum(d.gate == "2" and d.verdict == "pass" for d in run.decisions),
                validated_combos=len(run.winners),
            )
            if alerts:
                run.alerts.extend(alerts)
                if any(a.startswith(("project_cap", "checkpoint")) for a in alerts):
                    stopped = True
                else:
                    day += 1
                    day_platform = 0
                    day_sales = []
                break
        for aid, group in groups.items():
            children = [ad for ad in ads if ad.angle_id == aid]
            if stages[aid] == "1":
                if any(states[ad.id] == "testing" for ad in children):
                    continue
                if not any(states[ad.id] == "pass" for ad in children):
                    stages[aid] = "killed"
                    continue
                stages[aid] = "2"
            if stages[aid] not in ("2", "3", "C"):
                continue
            group.gate = stages[aid]
            snapshots = [s for ad in children for s in histories[ad.id]]
            latest = max((s.ts for s in snapshots), default=now)
            total = aggregate(snapshots, group.id, latest)
            sales = [s for s in run.sales if s.matched_entity_id in {ad.id for ad in children}]
            decision = evaluate(
                group,
                total,
                sales,
                6000,
                r,
                now,
                confirmation_start_cents=confirmation_starts.get(aid),
            )
            decision.id = f"s{seed}-d{len(run.decisions)}"
            run.decisions.append(decision)
            if decision.verdict == "pass":
                if stages[aid] == "2":
                    stages[aid] = "3"
                elif stages[aid] == "3" and r.gate_C is not None:
                    confirmation_starts[aid] = decision.metrics_json["spend_gross"]
                    stages[aid] = "C"
                else:
                    stages[aid] = "validated"
                    run.winners.append(aid)
            elif decision.verdict == "kill":
                stages[aid] = "killed"
                run.excess_cents += max(
                    0, decision.metrics_json["spend_gross"] - decision.metrics_json["cap_cents"]
                )
            elif decision.metrics_json["spend_gross"] >= decision.metrics_json["cap_cents"]:
                # G3 com poucas vendas: parar no teto para revisão, nunca continuar gastando.
                stages[aid] = "hold"
                run.alerts.append(f"{aid}: teto com vendas insuficientes; revisão humana")
        true_winners = {c.angle_id for c in p.creatives if p.truth[c.id].winner}
        run.killed_winners = sorted(
            aid
            for aid in true_winners
            if all(states[e.id] == "kill" for e in ads if e.angle_id == aid)
            or stages[aid] == "killed"
        )
    for e in p.entities:
        e.status = "paused"
    return run


def persist(run: Run, database: Path) -> None:
    if database.exists():
        raise ValueError("Banco de simulação já existe; escolha outro caminho")
    connection = connect(database)
    try:
        migrate(connection)
        with connection:
            for records in [
                run.population.offers,
                run.population.angles,
                run.population.creatives,
                run.population.entities,
                run.snapshots,
                run.sales,
                run.decisions,
            ]:
                for record in records:
                    Repository(connection, type(record)).add(record)
    finally:
        connection.close()


def confirmation_stats(run: Run) -> dict:
    """Ground truth is expected net revenue/cost, not the sampled outcome or role label.

    Equal impression allocation across the combo's creatives, fixed 6000 commission,
    15% refund and 13% media tax match the existing synthetic traffic model.
    """
    truth = {}
    for angle in run.population.angles:
        creatives = [c for c in run.population.creatives if c.angle_id == angle.id]
        signals = [run.population.truth[c.id] for c in creatives]
        expected_revenue = sum(
            t.ctr * 0.92 * t.checkout * t.purchase * 5100 * 1000 for t in signals
        )
        expected_cost = sum(t.cpm_cents * 1.13 for t in signals)
        truth[angle.id] = expected_revenue > expected_cost
    winners = {key for key, value in truth.items() if value}
    losers = set(truth) - winners
    validated = set(run.winners)
    return {
        "truth": dict(sorted(truth.items())),
        "true_winners": len(winners),
        "true_losers": len(losers),
        "true_validations": len(validated & winners),
        "false_validations": len(validated & losers),
        "missed_winners": len(winners - validated),
        "spend_gross_cents": run.summary()["spend_gross_cents"],
    }
