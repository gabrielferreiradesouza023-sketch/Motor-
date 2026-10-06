"""Fórmulas oficiais da seção 4. Dinheiro em centavos, taxas como frações."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from arb.models import MetricSnapshot, SaleEvent


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


def rev_expected(sales: Iterable[SaleEvent], refund_rate: float = 0.15) -> int:
    commission = sum(s.commission_cents for s in sales if s.status == "approved")
    return int(
        (Decimal(commission) * (1 - Decimal(str(refund_rate)))).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
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
) -> dict:
    sales = list(sales)
    gross = spend_gross(snapshot.spend_platform_cents, media_tax_rate)
    revenue = rev_expected(sales, refund_rate)
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
