"""Portão 0: ranking sem mídia e proposta de aprovação sem exposição."""

import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from arb.config import Policy
from arb.db import Repository
from arb.models import PRODUCER_FIELDS, AdObservation, Approval, Offer, OfferIntake
from arb.rules import load_rules


def rank(
    intake: list[OfferIntake],
    observations: list[AdObservation],
    policy_path: Path = Path("config/policy.yaml"),
) -> tuple[list[Offer], dict[str, list[str]]]:
    policy = Policy.model_validate(yaml.safe_load(policy_path.read_text()))
    r = load_rules().gate_0
    known = {i.offer.id for i in intake}
    if any(a.offer_id not in known for a in observations):
        raise ValueError("Observação referencia oferta desconhecida")
    ranked = []
    rejected = {}
    for item in intake:
        offer = producer_offer(item)
        reasons = []
        if offer.niche not in policy.allowed_niches or offer.niche in policy.forbidden_niches:
            reasons.append("nicho fora da lista permitida")
        if not offer.allows_paid_traffic or offer.producer_paid_traffic_ok is False:
            reasons.append("produtor não permite tráfego pago")
        if offer.commission_brl_cents < r.min_commission_cents:
            reasons.append("comissão abaixo do mínimo")
        if offer.language != "es" or not item.native_spanish:
            reasons.append("página não validada em espanhol nativo")
        if reasons:
            rejected[offer.id] = reasons
            continue
        advertisers = {
            a.advertiser_id
            for a in observations
            if a.offer_id == offer.id and a.active and (a.observed_at - a.first_seen).days >= 30
        }
        normalized = {
            "commission": min(
                offer.commission_brl_cents
                * (
                    1
                    - (
                        offer.producer_refund_rate
                        if offer.producer_refund_rate is not None
                        else 0.15
                    )
                )
                / 10000,
                1,
            ),
            "market_proof": min(
                (offer.advertisers_30d if offer.advertisers_30d is not None else len(advertisers))
                / 5,
                1,
            ),
            "sales_page": (item.sales_page_quality - 1) / 4,
            "popularity": item.popularity / 100,
        }
        positive_weights = sum(r.weights[name] for name in normalized)
        score = sum(r.weights[name] * value for name, value in normalized.items())
        score = max(
            0,
            min(100, score / positive_weights * 100 + r.weights["policy_risk"] * item.policy_risk),
        )
        ranked.append(offer.model_copy(update={"score": round(score, 2)}))
    ranked.sort(key=lambda o: (-o.score, o.id))
    return ranked, rejected


def propose(
    connection: sqlite3.Connection,
    ranked: list[Offer],
    directory: Path = Path("ops/approvals/pending"),
) -> Path:
    if not ranked:
        raise ValueError("Nenhuma oferta elegível; não gerar aprovação vazia")
    top = ranked[: load_rules().gate_0.top_offers]
    plan = {"kind": "new_offer", "offers": [o.model_dump(mode="json") for o in top]}
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    approval = Approval(
        id=f"new-offer-{digest}",
        plan_hash=digest,
        kind="new_offer",
        summary="Avaliar ofertas: " + ", ".join(o.name for o in top),
        max_exposure_cents=0,
        status="pending",
    )
    payload = (
        json.dumps(
            {"approval": approval.model_dump(mode="json"), "plan": plan},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{approval.id}.json"
    if path.exists() and path.read_text() != payload:
        raise ValueError("Arquivo existente divergente; não sobrescrever decisão humana")
    approvals = Repository(connection, Approval)
    offers = Repository(connection, Offer)
    with connection:
        for offer in ranked:
            existing = offers.get(offer.id)
            if existing:
                updates = {
                    "score": offer.score,
                    **{
                        key: getattr(offer, key)
                        for key in PRODUCER_FIELDS
                        if getattr(offer, key) is not None
                    },
                }
                offers.update(existing.model_copy(update=updates))
            else:
                offers.add(offer)
        if not approvals.get(approval.id):
            approvals.add(approval)
    if not path.exists() and approvals.get(approval.id).status == "pending":
        path.write_text(payload)
    return path


def producer_offer(item: OfferIntake) -> Offer:
    updates = {}
    for key in PRODUCER_FIELDS:
        declared = getattr(item, key)
        nested = getattr(item.offer, key)
        if declared is not None:
            if nested is not None and nested != declared:
                raise ValueError("dados do produtor conflitantes no intake")
            updates[key] = declared
    return item.offer.model_copy(update=updates)


def producer_report(intake: list[OfferIntake]) -> dict:
    result = {}
    for item in intake:
        offer = producer_offer(item)
        provided = {
            key: getattr(offer, key) for key in PRODUCER_FIELDS if getattr(offer, key) is not None
        }
        if provided:
            result[offer.id] = {
                "declared": provided,
                "alerts": ["permissão declarada sem referência de evidência"]
                if offer.producer_paid_traffic_ok is True and not offer.evidence_ref
                else [],
                "commission_refund_basis": "producer"
                if offer.producer_refund_rate is not None
                else "default",
                "market_proof_basis": "producer"
                if offer.advertisers_30d is not None
                else "ad_observations",
                "conversion_use": "diagnostic_only; no unapproved score normalization",
                "evidence_verified": False,
            }
    return result
