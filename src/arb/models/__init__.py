"""Contratos públicos da F0. Valores monetários sempre em centavos inteiros."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

Identifier = Annotated[str, Field(min_length=1)]
Cents = Annotated[int, Field(strict=True, ge=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
Gate = Literal["0", "1", "2", "3", "T"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def timezone_required(cls, value):
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("timestamp precisa de fuso horário")
        return value


class Offer(Model):
    id: Identifier
    hotmart_product_id: Identifier
    name: Identifier
    niche: Identifier
    language: Identifier
    commission_brl_cents: Cents
    price_local: Cents  # centavos na moeda local
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    allows_paid_traffic: bool
    sales_page_url: HttpUrl
    affiliate_link: HttpUrl
    score: Annotated[float, Field(ge=0, le=100)]
    status: Literal["candidate", "approved", "testing", "validated", "killed"]


class Angle(Model):
    id: Identifier
    offer_id: Identifier
    hypothesis: Identifier
    promise: Identifier
    audience_pain: Identifier
    hook_line: Identifier
    status: Literal["candidate", "approved", "testing", "validated", "killed"]


class Creative(Model):
    id: Identifier
    angle_id: Identifier
    format: Literal["image", "video"]
    copy_primary: Identifier
    headline: Identifier
    asset_path: Identifier
    policy_lint: Literal["passed", "failed"]
    status: Literal["candidate", "approved", "testing", "validated", "killed"]


class Entity(Model):
    id: Identifier
    kind: Literal["campaign", "adset", "ad"]
    meta_id: Identifier | None = None
    parent_id: Identifier | None = None
    offer_id: Identifier
    angle_id: Identifier | None = None
    creative_id: Identifier | None = None
    geo: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    gate: Gate
    daily_budget_cents: Cents
    status: Literal["active", "paused"]


class MetricSnapshot(Model):
    entity_id: Identifier
    ts: datetime
    period_start: date | None = None
    impressions: Count
    video_3s_views: Count
    link_clicks: Count
    spend_platform_cents: Cents
    bridge_views: Count
    checkout_clicks: Count


class SaleEvent(Model):
    id: Identifier
    source: Literal["webhook", "csv"]
    hotmart_tx_id: Identifier
    ts: datetime
    commission_cents: Cents
    status: Literal["approved", "refunded", "chargeback"]
    tracking_param: Identifier | None = None
    matched_entity_id: Identifier | None = None


class Decision(Model):
    id: Identifier
    ts: datetime
    entity_id: Identifier
    gate: Gate
    verdict: Literal["pass", "kill", "insufficient_data", "hold"]
    metrics_json: dict[str, Any]
    rule_id: Identifier
    reason: Identifier


class Approval(Model):
    id: Identifier
    plan_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    kind: Literal["launch", "activate", "scale", "new_offer"]
    summary: Identifier
    max_exposure_cents: Cents
    status: Literal["pending", "approved", "rejected"]
    decided_at: datetime | None = None


class Action(Model):
    id: Identifier
    ts: datetime
    actor: Literal["engine", "human", "agent:codex", "agent:claude"]
    kind: Identifier
    payload_json: dict[str, Any]
    approval_id: Identifier | None = None
    live: bool
    result: Identifier


class AngleLearning(Model):
    id: Identifier
    angle_id: Identifier
    offer_id: Identifier
    niche: Identifier
    promise: Identifier
    audience_pain: Identifier
    hook_line: Identifier
    formats: list[Literal["image", "video"]]
    geo: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    gate: Gate
    verdict: Literal["pass", "kill"]
    metrics_json: dict[str, Any]
    reason: Identifier
    archived_at: datetime


class OfferIntake(Model):
    offer: Offer
    native_spanish: bool
    sales_page_quality: Annotated[int, Field(strict=True, ge=1, le=5)]
    popularity: Annotated[float, Field(ge=0, le=100)]
    policy_risk: Annotated[float, Field(ge=0, le=1)]


class AdObservation(Model):
    offer_id: Identifier
    advertiser_id: Identifier
    first_seen: date
    observed_at: date
    active: bool


class BridgeEvent(Model):
    id: Identifier
    kind: Literal["view", "checkout_click"]
    ad_id: Identifier
    geo: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    ts: datetime


class MetricAdjustment(Model):
    id: Identifier
    entity_id: Identifier
    ts: datetime
    period_start: date
    deltas: dict[
        Literal[
            "impressions",
            "video_3s_views",
            "link_clicks",
            "spend_platform_cents",
            "bridge_views",
            "checkout_clicks",
        ],
        Annotated[int, Field(strict=True)],
    ]
    reason: Identifier


class LaunchPlan(Model):
    """Entradas completas e imutáveis por hash; a execução revalida a elegibilidade."""

    offer: Offer
    angles: list[Angle]
    creatives: list[Creative]
    geo: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    daily_budget_cents: Annotated[int, Field(strict=True, gt=0, le=6000)]
    destination_url: HttpUrl
    entities: list[Entity]
    objective: Literal["InitiateCheckout"] = "InitiateCheckout"
    budget_type: Literal["ABO"] = "ABO"
    age_min: Literal[18] = 18
    age_max: Literal[65] = 65
    language: Literal["es"] = "es"
    interests: list[str] = Field(default_factory=list, max_length=0)


MODEL_TYPES = (
    Offer,
    Angle,
    Creative,
    Entity,
    MetricSnapshot,
    SaleEvent,
    Decision,
    Approval,
    Action,
    AngleLearning,
    OfferIntake,
    AdObservation,
    BridgeEvent,
    MetricAdjustment,
    LaunchPlan,
)


def contract_name(model: type[Model]) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", model.__name__).lower() + ".json"


def contract_text(model: type[Model]) -> str:
    return (
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def export_contracts(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for model in MODEL_TYPES:
        path = directory / contract_name(model)
        path.write_text(contract_text(model), encoding="utf-8")
        paths.append(path)
    return paths
