"""Portões determinísticos; avaliar nunca executa ações nem altera exposição."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import yaml

from arb.config import Rules
from arb.metrics import p_roi_positive, summarize
from arb.models import Decision, Entity, MetricSnapshot, SaleEvent


def load_rules(path: Path = Path("config/rules.yaml")) -> Rules:
    return Rules.model_validate(yaml.safe_load(path.read_text()))


def evaluate(
    entity: Entity,
    snapshot: MetricSnapshot,
    sales: list[SaleEvent],
    commission_cents: int,
    rules: Rules,
    now: datetime,
    *,
    video: bool = True,
    media_tax_rate: float = 0.13,
    refund_rate: float = 0.15,
    confirmation_start_cents: int | None = None,
    confirmed: bool = False,
) -> Decision:
    if now.utcoffset() is None or snapshot.ts > now:
        raise ValueError("tempo inválido")
    if snapshot.entity_id != entity.id:
        raise ValueError("snapshot pertence a outra entidade")
    metrics = summarize(
        snapshot, sales, video=video, media_tax_rate=media_tax_rate, refund_rate=refund_rate
    )
    gate = entity.gate
    spent = metrics["spend_gross"]
    if gate in ("3", "T", "C"):
        metrics["p_roi_positive"] = p_roi_positive(
            metrics["sales"], spent, commission_cents * (1 - refund_rate)
        )
    if rules.gate_C is not None and gate in ("3", "T", "C"):
        metrics["confirmation_geo"] = entity.geo
    if gate == "C":
        if commission_cents <= 0:
            raise ValueError("comissão precisa ser positiva")
        if rules.gate_C is None:
            raise ValueError("Portão C desligado")
        if (
            confirmation_start_cents is None
            or type(confirmation_start_cents) is not int
            or not 0 <= confirmation_start_cents <= spent
        ):
            raise ValueError("Portão C exige gasto inicial confirmado no mesmo geo")
        cap = confirmation_start_cents + rules.gate_C.cap_cents
        sampled = metrics["sales"] >= rules.gate_C.min_sales_total
        metrics["confirmation_start_cents"] = confirmation_start_cents
    elif gate == "1":
        cap = rules.gate_1.cap_cents
        sampled = snapshot.impressions >= rules.gate_1.min_impressions
    elif gate == "2":
        cap = rules.gate_2.cap_cents
        sampled = snapshot.bridge_views >= rules.gate_2.min_bridge_views
    elif gate in ("3", "T"):
        if commission_cents <= 0:
            raise ValueError("comissão precisa ser positiva")
        cap = (
            rules.gate_T.cap_cents
            if gate == "T"
            else rules.gate_3.commission_cap_multiplier * int(commission_cents * (1 - refund_rate))
        )
        sampled = metrics["sales"] >= rules.gate_3.min_sales
    else:
        raise ValueError("Portão 0 pertence ao scout; evaluator suporta 1/2/3/T/C")
    stale = now - snapshot.ts > timedelta(hours=rules.controls.stale_after_hours)
    verdict, rule_id, reason = "hold", f"g{gate}.hold", "Entre limites; continuar até o teto"
    # Teto é a única exceção à exigência de amostra. G3 com vendas não é kill automático.
    cap_kill = spent >= cap and (gate in ("1", "2", "C") or metrics["sales"] == 0)
    if stale:
        verdict = "kill" if cap_kill else "insufficient_data"
        rule_id = f"g{gate}.cap" if cap_kill else "data.stale"
        reason = "Teto atingido com dados atrasados" if cap_kill else "Dados atrasados: alerta"
    elif not sampled:
        verdict = "kill" if cap_kill else "insufficient_data"
        rule_id = f"g{gate}.cap" if cap_kill else f"g{gate}.sample"
        reason = "Teto sem amostra suficiente" if cap_kill else "Amostra mínima não atingida"
    elif gate == "1":
        r = rules.gate_1
        if metrics["ctr_link"] < r.kill_ctr_link or (
            video and metrics["hook_rate"] < r.kill_hook_rate
        ):
            verdict, rule_id, reason = "kill", "g1.signal", "CTR ou hook abaixo do mínimo"
        elif metrics["ctr_link"] >= r.pass_ctr_link and (
            not video or metrics["hook_rate"] >= r.pass_hook_rate
        ):
            verdict, rule_id, reason = "pass", "g1.pass", "Atenção confirmada com amostra mínima"
    elif gate == "2":
        if metrics["bridge_rate"] < rules.gate_2.kill_bridge_rate:
            verdict, rule_id, reason = "kill", "g2.signal", "Ponte sem intenção suficiente"
        elif metrics["bridge_rate"] >= rules.gate_2.pass_bridge_rate:
            verdict, rule_id, reason = "pass", "g2.pass", "Intenção confirmada"
    elif gate == "C":
        c = rules.gate_C
        if (
            metrics["roi_expected"] is not None
            and metrics["p_roi_positive"] is not None
            and metrics["roi_expected"] >= c.min_roi
            and metrics["p_roi_positive"] >= c.min_p_roi_positive
        ):
            verdict, rule_id, reason = "pass", "gC.pass", "Vencedor confirmado no mesmo geo"
    else:
        if (
            metrics["roi_expected"] is not None
            and metrics["roi_expected"] >= rules.gate_3.min_roi
            and metrics["cpc_gross"] is not None
            and metrics["epc"] is not None
            and metrics["cpc_gross"] <= metrics["epc"] * rules.gate_3.epc_factor
        ):
            verdict, rule_id, reason = "pass", f"g{gate}.pass", "Combo validado: vendas, ROI e CPC"
    if verdict in ("hold", "insufficient_data") and cap_kill:
        verdict, rule_id, reason = "kill", f"g{gate}.cap", "Teto atingido sem passar"
    # ADR-016: G3/T com vendas mas sem validação não pode gastar indefinidamente.
    hard_cap = int(cap * rules.gate_3.hard_cap_multiplier) if gate in ("3", "T") else None
    if hard_cap is not None and verdict != "pass" and spent >= hard_cap:
        verdict, rule_id, reason = (
            "kill",
            f"g{gate}.hard_cap",
            "Teto rígido atingido sem validar o combo",
        )
    if rules.gate_C is not None and gate == "3" and verdict == "pass":
        reason = "Candidato: exige confirmação C antes de escala/transferência"
    if rules.gate_C is not None and gate == "T" and not confirmed:
        verdict, rule_id, reason = "insufficient_data", "gT.confirmation", "Exige pass em C"
        if spent >= cap:
            verdict, rule_id, reason = "kill", "gT.cap", "Teto sem confirmação C"
    metrics["sample_sufficient"] = sampled
    metrics["cap_cents"] = cap
    metrics["hard_cap_cents"] = hard_cap
    metrics["stale"] = stale
    return Decision(
        id=str(uuid4()),
        ts=now,
        entity_id=entity.id,
        gate=gate,
        verdict=verdict,
        metrics_json=metrics,
        rule_id=rule_id,
        reason=reason,
    )


def controls(
    rules: Rules,
    *,
    day_spend_cents: int,
    day_revenue_cents: int,
    total_spend_cents: int,
    passed_gate_2: int,
    validated_combos: int,
) -> list[str]:
    """Retorna motivos de pausa/revisão. Nunca ativa ou aumenta orçamento."""
    r = rules.controls
    alerts = []
    if day_spend_cents >= int(r.daily_cap_cents * r.pause_fraction):
        alerts.append("daily_cap: pausar até o próximo dia São Paulo")
    if day_spend_cents > r.emergency_min_spend_cents:
        roi = (day_revenue_cents - day_spend_cents) / day_spend_cents
        if roi < r.emergency_roi:
            alerts.append("emergency: ROI diário abaixo do limite; revisão humana")
    if total_spend_cents >= r.checkpoint_cents and passed_gate_2 == 0:
        alerts.append("checkpoint: nenhum Portão 2; revisar ofertas, ângulos ou nicho")
    if total_spend_cents >= r.total_cap_cents:
        alerts.append(
            "project_cap: teto total; encerrar afiliado"
            if validated_combos == 0
            else "project_cap: teto total; aguardar novo aporte aprovado"
        )
    return alerts


def scale_allowed(
    rules: Rules,
    current_cents: int,
    proposed_cents: int,
    last_increase: datetime,
    now: datetime,
    *,
    approved: bool,
    confirmed: bool = False,
) -> bool:
    return (
        approved
        and (rules.gate_C is None or confirmed)
        and current_cents > 0
        and proposed_cents > current_cents
        and proposed_cents <= int(current_cents * (1 + rules.controls.max_scale_fraction))
        and now - last_increase >= timedelta(hours=rules.controls.scale_interval_hours)
    )


def confirmation_context(entity: Entity, decisions: list[Decision]) -> tuple[int | None, bool]:
    """A referência e o vencedor pertencem à mesma entidade/geo, nunca a um candidato."""
    relevant = sorted(
        (
            d
            for d in decisions
            if d.entity_id == entity.id and d.metrics_json.get("confirmation_geo") == entity.geo
        ),
        key=lambda d: (d.ts, d.id),
    )
    baseline = next(
        (d.metrics_json["spend_gross"] for d in relevant if d.gate == "3" and d.verdict == "pass"),
        None,
    )
    confirmations = [d for d in relevant if d.gate == "C"]
    return baseline, bool(confirmations and confirmations[-1].verdict == "pass")


def winner_gates(rules: Rules) -> set[str]:
    return {"C", "T"} if rules.gate_C is not None else {"3", "T"}
