"""Importação semiautomática estrita; sem scraping e sem chamadas externas."""

import csv
from pathlib import Path

from arb.models import PRODUCER_FIELDS, AdObservation, Offer, OfferIntake

OFFER_HEADERS = (
    "id",
    "hotmart_product_id",
    "name",
    "niche",
    "language",
    "commission_brl_cents",
    "price_local",
    "currency",
    "allows_paid_traffic",
    "sales_page_url",
    "affiliate_link",
    "native_spanish",
    "sales_page_quality",
    "popularity",
    "policy_risk",
)
AD_HEADERS = ("offer_id", "advertiser_id", "first_seen", "observed_at", "active")


def rows(
    path: Path, headers: tuple[str, ...], optional: tuple[str, ...] = ()
) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames or []
        if (
            fields[: len(headers)] != list(headers)
            or len(fields) != len(set(fields))
            or any(key not in optional for key in fields[len(headers) :])
        ):
            raise ValueError(f"Cabeçalho inválido em {path.name}; esperado: {','.join(headers)}")
        result = list(reader)
    if any(
        None in row
        or any(
            value is None or (key not in optional and not value.strip())
            for key, value in row.items()
        )
        for row in result
    ):
        raise ValueError(f"Linha incompleta ou colunas excedentes em {path.name}")
    return result


def boolean(value: str) -> bool:
    if value not in ("true", "false"):
        raise ValueError("Booleano precisa ser true ou false")
    return value == "true"


def import_offers(path: Path) -> list[OfferIntake]:
    result = []
    seen = set()
    for number, row in enumerate(rows(path, OFFER_HEADERS, PRODUCER_FIELDS), 2):
        try:
            if row["id"] in seen:
                raise ValueError("id duplicado")
            seen.add(row["id"])
            producer = {}
            for key in PRODUCER_FIELDS:
                value = row.pop(key, "").strip()
                if not value:
                    continue
                producer[key] = (
                    boolean(value)
                    if key == "producer_paid_traffic_ok"
                    else float(value)
                    if key in {"producer_refund_rate", "producer_conversion_rate"}
                    else int(value)
                    if key == "advertisers_30d"
                    else value
                )
            if producer.get("producer_paid_traffic_ok") is False:
                row["allows_paid_traffic"] = "false"
            assessment = {
                key: row.pop(key)
                for key in ("native_spanish", "sales_page_quality", "popularity", "policy_risk")
            }
            for key in ("commission_brl_cents", "price_local"):
                row[key] = int(row[key])
            row["allows_paid_traffic"] = boolean(row["allows_paid_traffic"])
            result.append(
                OfferIntake(
                    offer=Offer(**row, **producer, score=0, status="candidate"),
                    **producer,
                    native_spanish=boolean(assessment["native_spanish"]),
                    sales_page_quality=int(assessment["sales_page_quality"]),
                    popularity=float(assessment["popularity"]),
                    policy_risk=float(assessment["policy_risk"]),
                )
            )
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Oferta inválida na linha {number}: {exc.__class__.__name__}"
            ) from exc
    return result


def import_adlibrary(path: Path) -> list[AdObservation]:
    result = []
    seen = set()
    for number, row in enumerate(rows(path, AD_HEADERS), 2):
        try:
            row["active"] = boolean(row["active"])
            observation = AdObservation(**row)
            key = (observation.offer_id, observation.advertiser_id)
            if key in seen or observation.first_seen > observation.observed_at:
                raise ValueError("duplicata ou datas invertidas")
            seen.add(key)
            result.append(observation)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Observação inválida na linha {number}") from exc
    return result
