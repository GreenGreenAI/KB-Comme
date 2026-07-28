"""Deterministic pairing of private forward quotes with their origin spot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from tradeflow.domain.datasets import (
    ForwardQuoteSpotRef,
    ObservedForwardQuoteDataset,
)
from tradeflow.domain.snapshot import require_aware


class ForwardQuoteHistoryError(ValueError):
    """Quote history cannot be aligned without guessing or future leakage."""


@dataclass(frozen=True)
class OriginSpotRate:
    observed_at: datetime
    rate: Decimal

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "origin spot observed_at")
        if self.rate <= 0:
            raise ValueError("origin spot rate must be positive")


@dataclass(frozen=True)
class PairedForwardRateHistory:
    observed_at: tuple[datetime, ...]
    spot_rates: tuple[Decimal, ...]
    forward_rates: tuple[Decimal, ...]
    provider_id: str
    tenor_days: int
    quote_basis: str = "observed_forward_quote"


def pair_company_forward_history(
    dataset: ObservedForwardQuoteDataset,
    spot_rates: Mapping[ForwardQuoteSpotRef, OriginSpotRate],
    *,
    company_id: str,
    provider_id: str,
    base_currency: str,
    counter_currency: str,
    side: str,
    notional: Decimal,
    tenor_days: int,
    case_id: str | None = None,
) -> PairedForwardRateHistory:
    """Build a constant-tenor history without crossing company/provider scope.

    Each returned spot is identified by the exact snapshot carried by its
    quote. A spot observed after the quote is rejected as look-ahead leakage.
    Multiple quotes at one instant are rejected instead of selecting a
    favourable rate.
    """
    if not company_id or not provider_id:
        raise ForwardQuoteHistoryError("company_id and provider_id are required")
    if side not in {"buy", "sell"}:
        raise ForwardQuoteHistoryError("side must be buy or sell")
    if notional <= 0:
        raise ForwardQuoteHistoryError("notional must be positive")
    if tenor_days <= 0:
        raise ForwardQuoteHistoryError("tenor_days must be positive")

    selected = []
    for quote in dataset.records:
        quote_tenor = (quote.settlement_date - quote.observed_at.date()).days
        if (
            quote.company_id != company_id
            or quote.provider_id != provider_id
            or quote.base_currency != base_currency
            or quote.counter_currency != counter_currency
            or quote.side != side
            or notional < quote.notional_min
            or notional > quote.notional_max
            or quote_tenor != tenor_days
            or (case_id is not None and case_id not in quote.case_ids)
        ):
            continue
        selected.append(quote)

    if not selected:
        raise ForwardQuoteHistoryError(
            "no company-applicable forward quotes match the requested history"
        )
    selected.sort(key=lambda quote: quote.observed_at)
    moments = [quote.observed_at for quote in selected]
    if len(set(moments)) != len(moments):
        raise ForwardQuoteHistoryError(
            "multiple matching forward quotes share an observation instant"
        )

    aligned_spot: list[Decimal] = []
    aligned_forward: list[Decimal] = []
    for quote in selected:
        try:
            spot = spot_rates[quote.origin_spot_snapshot]
        except KeyError:
            raise ForwardQuoteHistoryError(
                f"origin spot snapshot is unavailable for quote {quote.quote_id}"
            ) from None
        require_aware(spot.observed_at, "origin spot observed_at")
        if spot.observed_at > quote.observed_at:
            raise ForwardQuoteHistoryError(
                f"origin spot for quote {quote.quote_id} leaks future data"
            )
        aligned_spot.append(spot.rate)
        aligned_forward.append(quote.contract_rate)

    return PairedForwardRateHistory(
        observed_at=tuple(moments),
        spot_rates=tuple(aligned_spot),
        forward_rates=tuple(aligned_forward),
        provider_id=provider_id,
        tenor_days=tenor_days,
    )
