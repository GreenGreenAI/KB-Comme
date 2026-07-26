"""Projection from internal calculation vocabulary to the response contract.

The calculation layer and the response contract use different names on purpose
(ADR-0002). This module is the single place the two vocabularies meet, and it
only renames and collects values. It never recalculates, rounds or approximates,
so a projected figure is always identical to the tool output it came from.
"""

from typing import Any

from tradeflow.domain.models import CurrencyExposure

CASHFLOW_FIELD_MAP = {
    "economic_offset": "natural_hedge_amount",
    "maturity_matched_amount": "maturity_matched_amount",
    "trade_net_exposure": "net_exposure",
    "peak_funding_gap": "funding_gap",
    "timeline": "events",
}


def project_cashflow_analysis(
    exposures: tuple[CurrencyExposure, ...],
) -> dict[str, Any]:
    """Build the `cashflow_analysis` block of the response contract.

    Figures are reported per currency so a reader can tell which currency a
    number belongs to, and `net_exposure` keeps its sign: negative means
    payments exceed receipts.
    """
    return {
        "natural_hedge_amount": [
            {"currency": item.currency, "amount": item.economic_offset}
            for item in exposures
        ],
        "maturity_matched_amount": [
            {"currency": item.currency, "amount": item.maturity_matched_amount}
            for item in exposures
        ],
        "net_exposure": [
            {"currency": item.currency, "amount": item.trade_net_exposure}
            for item in exposures
        ],
        "funding_gap": [
            {"currency": item.currency, "peak_amount": item.peak_funding_gap}
            for item in exposures
        ],
        "events": [
            {
                "currency": point.currency,
                "event_date": point.event_date,
                "case_id": point.case_id,
                "inflow": point.inflow,
                "outflow": point.outflow,
                "running_balance": point.running_balance,
                "funding_gap": point.funding_gap,
            }
            for item in exposures
            for point in item.timeline
        ],
    }
