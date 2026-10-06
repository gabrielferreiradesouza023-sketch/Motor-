"""Tráfego sintético com verdade plantada, independente das regras do motor."""

import random
from dataclasses import dataclass, replace
from datetime import datetime

from arb.config import load_sim_profiles
from arb.models import Angle, Creative, Entity, MetricSnapshot, Offer, SaleEvent


@dataclass(frozen=True)
class Truth:
    ctr: float
    hook: float
    checkout: float
    purchase: float
    cpm_cents: int
    winner: bool = False
    role: str = "loser"


@dataclass
class Population:
    offers: list[Offer]
    angles: list[Angle]
    creatives: list[Creative]
    entities: list[Entity]
    truth: dict[str, Truth]


def population(
    seed: int, offers: int = 3, angles: int = 3, creatives: int = 3, *, profile: str = "planted"
) -> Population:
    if min(offers, angles, creatives) < 1:
        raise ValueError("dimensões precisam ser positivas")
    rng = random.Random(seed)
    result = Population([], [], [], [], {})
    for i in range(offers):
        oid = f"o{i}"
        result.offers.append(
            Offer(
                id=oid,
                hotmart_product_id=f"sim-{i}",
                name=f"Curso simulado {i}",
                niche="excel_produtividade",
                language="es",
                commission_brl_cents=6000,
                price_local=15000,
                currency="BRL",
                allows_paid_traffic=True,
                sales_page_url="https://example.com/sales",
                affiliate_link="https://example.com/buy",
                score=70,
                status="testing",
            )
        )
        result.entities.append(
            Entity(
                id=f"campaign-{oid}",
                kind="campaign",
                offer_id=oid,
                geo="CO",
                gate="0",
                daily_budget_cents=0,
                status="paused",
            )
        )
        for j in range(angles):
            aid = f"{oid}-a{j}"
            result.angles.append(
                Angle(
                    id=aid,
                    offer_id=oid,
                    hypothesis="Prática guiada",
                    promise="Aprender Excel",
                    audience_pain="Tempo",
                    hook_line="Planilhas úteis",
                    status="testing",
                )
            )
            result.entities.append(
                Entity(
                    id=f"set-{aid}",
                    kind="adset",
                    offer_id=oid,
                    parent_id=f"campaign-{oid}",
                    angle_id=aid,
                    geo="CO",
                    gate="2",
                    daily_budget_cents=1000,
                    status="active",
                )
            )
            for k in range(creatives):
                cid = f"{aid}-c{k}"
                result.creatives.append(
                    Creative(
                        id=cid,
                        angle_id=aid,
                        format="video",
                        copy_primary="Práctica guiada",
                        headline="Excel",
                        asset_path="sim/video.mp4",
                        policy_lint="passed",
                        status="testing",
                    )
                )
                result.entities.append(
                    Entity(
                        id=cid,
                        kind="ad",
                        parent_id=f"set-{aid}",
                        offer_id=oid,
                        angle_id=aid,
                        creative_id=cid,
                        geo="CO",
                        gate="1",
                        daily_budget_cents=1000,
                        status="active",
                    )
                )
                winner = i == 0 and j == 0
                if winner:
                    truth = Truth(0.025, 0.4, 0.3, 0.3, 700, True)
                elif j == 0:
                    truth = Truth(0.018, 0.35, 0.04, 0.03, 1000)
                elif j == 1:
                    truth = Truth(0.02, 0.35, 0.24, 0.0, 1000)
                else:
                    truth = Truth(rng.uniform(0.002, 0.006), 0.18, 0.04, 0.01, 1000)
                result.truth[cid] = truth
    profiles = load_sim_profiles()
    if profile not in type(profiles).model_fields:
        raise ValueError("perfil desconhecido")
    if profile == "planted":
        for cid, truth in result.truth.items():
            role = (
                "winner"
                if truth.winner
                else "borderline_winner"
                if cid.startswith("o1-a0-")
                else "loser"
            )
            result.truth[cid] = replace(truth, role=role)
    else:
        if len(result.angles) < 2:
            raise ValueError("perfil realista exige ao menos dois ângulos")
        sampler = random.Random(seed ^ 0xA8B)
        winner, borderline = sampler.sample([a.id for a in result.angles], 2)
        trap = next((a.id for a in result.angles if a.id not in {winner, borderline}), None)
        distributions = getattr(profiles, profile)
        for creative in result.creatives:
            role = (
                "winner"
                if creative.angle_id == winner
                else "borderline_winner"
                if creative.angle_id == borderline
                else "attention_trap"
                if creative.angle_id == trap
                else "loser"
            )
            dist = getattr(distributions, role)
            result.truth[creative.id] = Truth(
                ctr=sampler.uniform(*dist.ctr),
                hook=sampler.uniform(*dist.hook),
                checkout=sampler.uniform(*dist.checkout),
                purchase=sampler.uniform(*dist.purchase),
                cpm_cents=sampler.randint(*dist.cpm_cents),
                winner=role == "winner",
                role=role,
            )
    return result


def binomial(rng: random.Random, count: int, probability: float) -> int:
    return sum(rng.random() < probability for _ in range(count))


def traffic(
    entity: Entity, truth: Truth, rng: random.Random, ts: datetime, *, impressions: int = 100
) -> tuple[MetricSnapshot, list[SaleEvent]]:
    """Um intervalo não sobreposto. Custos vêm do CPM; taxas verdadeiras não usam regras."""
    clicks = binomial(rng, impressions, truth.ctr)
    visits = binomial(rng, clicks, 0.92)
    checkout = binomial(rng, visits, truth.checkout)
    sales_count = binomial(rng, checkout, truth.purchase)
    platform = round(impressions * truth.cpm_cents / 1000 * rng.uniform(0.85, 1.15))
    snapshot = MetricSnapshot(
        entity_id=entity.id,
        ts=ts,
        impressions=impressions,
        video_3s_views=binomial(rng, impressions, truth.hook),
        link_clicks=clicks,
        spend_platform_cents=platform,
        bridge_views=visits,
        checkout_clicks=checkout,
    )
    sales = []
    for n in range(sales_count):
        sid = f"sim-{entity.id}-{ts.isoformat()}-{n}"
        sales.append(
            SaleEvent(
                id=sid,
                source="csv",
                hotmart_tx_id=sid,
                ts=ts,
                commission_cents=6000,
                status="approved",
                tracking_param=entity.id,
                matched_entity_id=entity.id,
            )
        )
    return snapshot, sales


def aggregate(snapshots: list[MetricSnapshot], entity_id: str, ts: datetime) -> MetricSnapshot:
    fields = (
        "impressions",
        "video_3s_views",
        "link_clicks",
        "spend_platform_cents",
        "bridge_views",
        "checkout_clicks",
    )
    return MetricSnapshot(
        entity_id=entity_id, ts=ts, **{f: sum(getattr(s, f) for s in snapshots) for f in fields}
    )
