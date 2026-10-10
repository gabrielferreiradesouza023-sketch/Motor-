"""Fórmulas oficiais da seção 4. Dinheiro em centavos, taxas como frações."""

import math
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from arb.config import load_settings
from arb.models import Entity, MetricSnapshot, Offer, SaleEvent


def divide(numerator: int | float, denominator: int | float) -> float | None:
    return numerator / denominator if denominator else None


def spend_gross(spend_platform_cents: int, media_tax_rate: float = 0.13) -> int:
    return int(
        (Decimal(spend_platform_cents) * (1 + Decimal(str(media_tax_rate)))).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def hook_rate(video_3s_views: int, impressions: int, *, video: bool = True) -> float | None:
    return divide(video_3s_views, impressions) if video else None


def ctr_link(link_clicks: int, impressions: int) -> float | None:
    return divide(link_clicks, impressions)


def cpc_gross(spend_gross_cents: int, link_clicks: int) -> float | None:
    return divide(spend_gross_cents, link_clicks)


def bridge_rate(checkout_clicks: int, bridge_views: int) -> float | None:
    return divide(checkout_clicks, bridge_views)


def effective_refund_rate(
    offer: Offer,
    own_sales: Iterable[SaleEvent],
    default: float | None = None,
    *,
    min_sales: int | None = None,
) -> float:
    if default is None or min_sales is None:
        settings = load_settings()
        default = settings.refund_rate if default is None else default
        min_sales = settings.refund_min_sales if min_sales is None else min_sales
    if offer.producer_refund_rate is None:
        return default
    unique = {}
    for sale in sorted(own_sales, key=lambda s: (s.ts, s.status != "approved", s.id)):
        unique[sale.hotmart_tx_id] = sale
    if len(unique) < min_sales:
        return max(offer.producer_refund_rate, default)
    return sum(s.status != "approved" for s in unique.values()) / len(unique)


def effective_refund_rates(
    offers: Iterable[Offer],
    entities: Iterable[Entity],
    sales: Iterable[SaleEvent],
    default: float | None = None,
    *,
    min_sales: int | None = None,
    exclude_ids: set[str] | None = None,
) -> dict[str, float]:
    entities = list(entities)
    sales = list(sales)
    result = {}
    for offer in offers:
        if offer.producer_refund_rate is None:
            continue
        own = {e.id for e in entities if e.offer_id == offer.id} - (exclude_ids or set())
        rate = effective_refund_rate(
            offer, [s for s in sales if s.matched_entity_id in own], default, min_sales=min_sales
        )
        result.update({e.id: rate for e in entities if e.offer_id == offer.id})
    return result


def rev_expected(
    sales: Iterable[SaleEvent],
    refund_rate: float = 0.15,
    *,
    refund_rates: dict[str, float] | None = None,
) -> int:
    commissions = {}
    for sale in sales:
        if sale.status == "approved":
            rate = (refund_rates or {}).get(sale.matched_entity_id, refund_rate)
            commissions[rate] = commissions.get(rate, 0) + sale.commission_cents
    return sum(
        int(
            (Decimal(commission) * (1 - Decimal(str(rate)))).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )
        for rate, commission in commissions.items()
    )


def epc(revenue_cents: int, bridge_views: int) -> float | None:
    return divide(revenue_cents, bridge_views)


def max_cpc(epc_cents: float | None, factor: float = 0.7) -> float | None:
    return None if epc_cents is None else epc_cents * factor


def roi_expected(revenue_cents: int, spend_gross_cents: int) -> float | None:
    return divide(revenue_cents - spend_gross_cents, spend_gross_cents)


def waste_ratio(excess_spend_cents: int, total_spend_cents: int) -> float | None:
    return divide(excess_spend_cents, total_spend_cents)


def cost_per_learning(spend_gross_cents: int, sampled_verdicts: int) -> float | None:
    return divide(spend_gross_cents, sampled_verdicts)


def cash_at_risk(remaining_cap_cents: int, day_spend_cents: int) -> int:
    return remaining_cap_cents - day_spend_cents


def summarize(
    snapshot: MetricSnapshot,
    sales: Iterable[SaleEvent],
    *,
    video: bool = True,
    media_tax_rate: float = 0.13,
    refund_rate: float = 0.15,
    refund_rates: dict[str, float] | None = None,
) -> dict:
    sales = list(sales)
    gross = spend_gross(snapshot.spend_platform_cents, media_tax_rate)
    revenue = rev_expected(sales, refund_rate, refund_rates=refund_rates)
    earnings = epc(revenue, snapshot.bridge_views)
    return {
        **snapshot.model_dump(mode="json"),
        "spend_gross": gross,
        "rev_expected": revenue,
        "hook_rate": hook_rate(snapshot.video_3s_views, snapshot.impressions, video=video),
        "ctr_link": ctr_link(snapshot.link_clicks, snapshot.impressions),
        "cpc_gross": cpc_gross(gross, snapshot.link_clicks),
        "bridge_rate": bridge_rate(snapshot.checkout_clicks, snapshot.bridge_views),
        "epc": earnings,
        "max_cpc": max_cpc(earnings),
        "roi_expected": roi_expected(revenue, gross),
        "sales": sum(s.status == "approved" for s in sales),
    }


def p_roi_positive(sales: int, spent_cents: int, net_commission_cents: float) -> float | None:
    """Gamma(1, 1 centavo) prior; survival Gamma(sales+1, spent+1) at 1/net.

    Integer shape reduces to Poisson CDF. Log terms avoid overflow/underflow.
    Zero spend/commission cannot establish profitability and returns None.
    """
    if type(sales) is not int or type(spent_cents) is not int or sales < 0 or spent_cents < 0:
        raise ValueError("contagens/gasto inválidos")
    if not math.isfinite(net_commission_cents) or net_commission_cents < 0:
        raise ValueError("comissão líquida inválida")
    if not spent_cents or not net_commission_cents:
        return None
    x = (spent_cents + 1) / net_commission_cents
    terms = [-x + n * math.log(x) - math.lgamma(n + 1) for n in range(sales + 1)]
    largest = max(terms)
    return min(1.0, math.exp(largest) * math.fsum(math.exp(t - largest) for t in terms))
