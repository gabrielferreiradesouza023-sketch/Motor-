"""Validação estrutural da configuração; regras de negócio começam somente na F1."""

from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Rate = Annotated[float, Field(ge=0, le=1)]
Geo = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Gate0(ConfigModel):
    min_commission_cents: PositiveInt
    top_offers: PositiveInt
    weights: dict[
        Literal["commission", "market_proof", "sales_page", "popularity", "policy_risk"], int
    ]

    @field_validator("weights")
    @classmethod
    def complete_weights(cls, value):
        if set(value) != {"commission", "market_proof", "sales_page", "popularity", "policy_risk"}:
            raise ValueError("pesos incompletos")
        return value


class Gate1(ConfigModel):
    cap_cents: PositiveInt
    min_impressions: PositiveInt
    kill_hook_rate: Rate
    kill_ctr_link: Rate
    pass_hook_rate: Rate
    pass_ctr_link: Rate

    @model_validator(mode="after")
    def thresholds(self):
        if self.kill_hook_rate >= self.pass_hook_rate or self.kill_ctr_link >= self.pass_ctr_link:
            raise ValueError("limiares invertidos")
        return self


class Gate2(ConfigModel):
    cap_cents: PositiveInt
    min_bridge_views: PositiveInt
    kill_bridge_rate: Rate
    pass_bridge_rate: Rate

    @model_validator(mode="after")
    def thresholds(self):
        if self.kill_bridge_rate >= self.pass_bridge_rate:
            raise ValueError("limiares invertidos")
        return self


class Gate3(ConfigModel):
    commission_cap_multiplier: PositiveInt
    min_sales: PositiveInt
    min_roi: Annotated[float, Field(ge=0)]
    epc_factor: Rate
    # ADR-016: acima de teto × multiplicador, G3/T sem validação morre mesmo com vendas.
    hard_cap_multiplier: Annotated[float, Field(gt=1, le=5)]


class GateT(ConfigModel):
    cap_cents: PositiveInt


class Controls(ConfigModel):
    daily_cap_cents: PositiveInt
    pause_fraction: Annotated[float, Field(gt=0, le=1)]
    emergency_roi: Annotated[float, Field(ge=-1, lt=0)]
    emergency_min_spend_cents: PositiveInt
    max_scale_fraction: Rate
    scale_interval_hours: PositiveInt
    stale_after_hours: PositiveInt
    checkpoint_cents: PositiveInt
    total_cap_cents: PositiveInt

    @model_validator(mode="after")
    def limits(self):
        if not self.daily_cap_cents <= self.checkpoint_cents < self.total_cap_cents:
            raise ValueError("tetos inconsistentes")
        return self


class Rules(ConfigModel):
    gate_0: Gate0
    gate_1: Gate1
    gate_2: Gate2
    gate_3: Gate3
    gate_T: GateT
    controls: Controls


class Settings(ConfigModel):
    lab_geos: Annotated[list[Geo], Field(min_length=1)]
    transfer_geos: Annotated[list[Geo], Field(min_length=1)]
    timezone: str
    currency: Literal["BRL"]
    cycles: Annotated[
        list[Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]], Field(min_length=1)
    ]
    media_tax_rate: Rate
    refund_rate: Rate
    refund_min_sales: PositiveInt
    meta_api_version: Annotated[str, Field(pattern=r"^v\d+\.\d+$")] | None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("fuso desconhecido") from exc
        return value


class Policy(ConfigModel):
    allowed_niches: Annotated[list[str], Field(min_length=1)]
    forbidden_niches: Annotated[list[str], Field(min_length=1)]
    banned_terms: Annotated[list[str], Field(min_length=1)]
    forbidden_practices: Annotated[list[str], Field(min_length=1)]

    @model_validator(mode="after")
    def disjoint(self):
        if set(self.allowed_niches) & set(self.forbidden_niches):
            raise ValueError("nicho permitido e proibido ao mesmo tempo")
        return self


def validate_config(root: Path) -> None:
    for name, model in [("rules", Rules), ("settings", Settings), ("policy", Policy)]:
        model.model_validate(yaml.safe_load((root / "config" / f"{name}.yaml").read_text()))
