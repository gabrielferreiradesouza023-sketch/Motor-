"""Planos pausados, determinísticos. Nenhuma escrita externa neste módulo."""

import hashlib
import json

from arb.models import Angle, Creative, Entity, LaunchPlan, Offer


def serialize(value: LaunchPlan) -> str:
    return json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def plan_hash(value: LaunchPlan) -> str:
    return hashlib.sha256(serialize(value).encode()).hexdigest()


def plan(
    offer: Offer,
    angles: list[Angle],
    creatives: list[Creative],
    *,
    geo: str,
    daily_budget_cents: int,
    destination_url: str,
) -> LaunchPlan:
    """Uma oferta, 1–3 ângulos, exatamente três criativos aprovados por ângulo.

    Verba diária é total por oferta, distribuída entre conjuntos ABO. O orçamento
    não autoriza exposição: criação e ativação são aprovações separadas.
    """
    if (
        offer.status != "approved"
        or not offer.allows_paid_traffic
        or offer.producer_paid_traffic_ok is False
    ):
        raise ValueError("oferta precisa estar aprovada e permitir tráfego pago")
    if geo not in {"CO", "PE"}:
        raise ValueError("laboratório restrito a CO/PE; transferência requer outro plano")
    if not 1 <= len(angles) <= 3 or len({a.id for a in angles}) != len(angles):
        raise ValueError("esperados 1–3 ângulos únicos")
    if len({c.id for c in creatives}) != len(creatives):
        raise ValueError("criativos duplicados")
    if any(a.offer_id != offer.id or a.status != "approved" for a in angles):
        raise ValueError("ângulo não aprovado ou de outra oferta")
    if any(
        c.angle_id not in {a.id for a in angles}
        or c.status != "approved"
        or c.policy_lint != "passed"
        for c in creatives
    ):
        raise ValueError("criativo não aprovado, sem lint ou de outro ângulo")
    if type(daily_budget_cents) is not int or not len(angles) <= daily_budget_cents <= 6000:
        raise ValueError("orçamento diário total inválido ou acima do teto")
    if not destination_url.startswith("https://"):
        raise ValueError("destino precisa ser ponte HTTPS")
    angles = sorted(angles, key=lambda a: a.id)
    creatives = sorted(creatives, key=lambda c: c.id)
    # IDs opacos estáveis, independentes de relógio e de ordem das entradas.
    prefix = hashlib.sha256(f"{offer.id}:{geo}".encode()).hexdigest()[:16]
    campaign = Entity(
        id=f"plan-{prefix}",
        kind="campaign",
        offer_id=offer.id,
        geo=geo,
        gate="0",
        daily_budget_cents=0,
        status="paused",
    )
    entities = [campaign]
    quotient, remainder = divmod(daily_budget_cents, len(angles))
    for index, angle in enumerate(angles):
        items = [c for c in creatives if c.angle_id == angle.id]
        if len(items) != 3:
            raise ValueError("cada ângulo exige exatamente três criativos")
        set_id = campaign.id + "-" + hashlib.sha256(angle.id.encode()).hexdigest()[:12]
        entities.append(
            Entity(
                id=set_id,
                kind="adset",
                parent_id=campaign.id,
                offer_id=offer.id,
                angle_id=angle.id,
                geo=geo,
                gate="2",
                daily_budget_cents=quotient + (index < remainder),
                status="paused",
            )
        )
        for creative in items:
            entities.append(
                Entity(
                    id=set_id + "-" + hashlib.sha256(creative.id.encode()).hexdigest()[:12],
                    kind="ad",
                    parent_id=set_id,
                    offer_id=offer.id,
                    angle_id=angle.id,
                    creative_id=creative.id,
                    geo=geo,
                    gate="1",
                    daily_budget_cents=0,
                    status="paused",
                )
            )
    return LaunchPlan(
        offer=offer,
        angles=angles,
        creatives=creatives,
        geo=geo,
        daily_budget_cents=daily_budget_cents,
        destination_url=destination_url,
        entities=entities,
    )


def validate_plan(value: LaunchPlan) -> LaunchPlan:
    expected = plan(
        value.offer,
        value.angles,
        value.creatives,
        geo=value.geo,
        daily_budget_cents=value.daily_budget_cents,
        destination_url=str(value.destination_url),
    )
    if serialize(expected) != serialize(value):
        raise ValueError("estrutura do plano divergente; regenere antes de aprovar")
    return expected
