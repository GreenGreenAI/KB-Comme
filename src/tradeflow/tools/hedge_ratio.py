"""Smallest hedge ratio that meets a loss limit, and what it costs (§5.3).

The optimizer answers one question: how much of the exposure must be hedged so
that profit stays above a floor at the adverse quantile. It never argues for
hedging — it returns the payoff at h=0, h* and h=1 side by side so the reader
compares rather than being steered (§21).

Two places generalize the spec, which is written as though the exposure were
always a receipt. With a signed exposure (ADR-0002) the adverse direction and
the loss probability both flip for a net payer, so both are derived from the
sign rather than assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from statistics import NormalDist
from typing import Iterable

from tradeflow.domain.models import HedgeMeasure
from tradeflow.tools.hedge import assert_all_usable

# Rates carry two decimals, profit is reported in whole won. Both modes travel
# with the result so a reader can reproduce the figures (§9.1).
RATE_EXPONENT = Decimal("0.01")
PROFIT_EXPONENT = Decimal("1")
ROUNDING = "ROUND_HALF_UP"

HEDGE_INSUFFICIENT = "HEDGE_INSUFFICIENT"

# Offered when no ratio reaches the floor. Reducing exposure or resetting the
# target are the remaining levers; a larger hedge is not one of them.
INSUFFICIENT_ALTERNATIVES = (
    "판가 전가",
    "결제조건 조정",
    "목표 손실한도 재설정",
)


class ExposureDirectionError(ValueError):
    """Raised when a hedge is requested for an exposure of zero."""


def z_one_sided(alpha: float) -> float:
    """Quantile z such that P(Z < -z) = alpha."""
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must sit strictly between 0 and 1, got {alpha}")
    return NormalDist().inv_cdf(1 - alpha)


def _rate(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(RATE_EXPONENT, rounding=ROUND_HALF_UP)


def _profit(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(PROFIT_EXPONENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PayoffPoint:
    """Profit at one rate, for one hedge ratio."""

    label: str
    rate: Decimal
    profit: Decimal


@dataclass(frozen=True)
class PayoffScenario:
    """One column of the comparison table."""

    ratio: float
    label: str
    points: tuple[PayoffPoint, ...]

    def at(self, label: str) -> PayoffPoint:
        for point in self.points:
            if point.label == label:
                return point
        raise KeyError(label)


@dataclass(frozen=True)
class BreakevenAnalysis:
    """Where profit turns negative, and how likely that is.

    `rate` is None when the floor cannot be crossed by any rate — a net payer
    whose baseline profit already exceeds what the exposure can lose.
    """

    rate: Decimal | None
    loss_probability: float


@dataclass(frozen=True)
class HedgeAnalysis:
    """The comparison, plus the smallest ratio that clears the floor."""

    optimal_ratio: float | None
    status: str | None
    alternatives: tuple[str, ...]
    comparison: tuple[PayoffScenario, ...]
    breakeven: BreakevenAnalysis
    measure_id: str
    adverse_rate: Decimal
    confidence_level: float
    z_score: float
    scaled_volatility: float
    rate_rounding: str
    profit_rounding: str

    @property
    def sufficient(self) -> bool:
        return self.optimal_ratio is not None


def _profit_at(
    rate: float,
    ratio: float,
    *,
    exposure: float,
    spot: float,
    contract_rate: float,
    cost_rate: float,
    baseline_profit: float,
) -> float:
    unhedged = (1.0 - ratio) * (rate - spot)
    hedged = ratio * (contract_rate - spot)
    cost = cost_rate * ratio * exposure * spot
    return baseline_profit + exposure * (unhedged + hedged) - cost


def analyze_hedge(
    measure: HedgeMeasure,
    *,
    net_exposure: Decimal,
    spot_rate: Decimal,
    baseline_profit: Decimal,
    scaled_volatility: float,
    profit_floor: Decimal = Decimal("0"),
    alpha: float = 0.05,
) -> HedgeAnalysis:
    """Solve for the smallest hedge ratio meeting the floor at the α-quantile.

    Substituting the adverse quantile into the payoff makes profit linear in
    the ratio, so the answer is closed-form rather than searched. A ratio above
    1 is never returned: hedging more than the exposure is a new speculative
    position, not less risk (§5.3).
    """
    assert_all_usable((measure,))

    if net_exposure == 0:
        raise ExposureDirectionError(
            "a hedge ratio is undefined for zero net exposure"
        )
    if measure.contract_rate is None:
        raise ValueError(
            f"{measure.measure_id}: a payoff needs a contracted rate"
        )

    exposure = float(net_exposure)
    spot = float(spot_rate)
    contract = float(measure.contract_rate)
    cost = float(measure.cost_rate or 0)
    baseline = float(baseline_profit)
    floor = float(profit_floor)

    z = z_one_sided(alpha)
    # A receipt loses when the rate falls; a payment loses when it rises.
    direction = 1.0 if exposure > 0 else -1.0
    adverse = spot * math.exp(-direction * z * scaled_volatility)
    favourable = spot * math.exp(direction * z * scaled_volatility)

    intercept = baseline + exposure * (adverse - spot)
    slope = exposure * ((contract - spot) - (adverse - spot) - cost * spot)

    if intercept >= floor:
        optimal: float | None = 0.0
    elif slope > 0:
        needed = (floor - intercept) / slope
        optimal = needed if needed <= 1.0 else None
    else:
        optimal = None

    ratios: list[tuple[float, str]] = [(0.0, "unhedged")]
    if optimal is not None and 0.0 < optimal < 1.0:
        ratios.append((optimal, "optimal"))
    ratios.append((1.0, "fully_hedged"))

    comparison = tuple(
        PayoffScenario(
            ratio=ratio,
            label=label,
            points=tuple(
                PayoffPoint(
                    label=point_label,
                    rate=_rate(rate),
                    profit=_profit(
                        _profit_at(
                            rate,
                            ratio,
                            exposure=exposure,
                            spot=spot,
                            contract_rate=contract,
                            cost_rate=cost,
                            baseline_profit=baseline,
                        )
                    ),
                )
                for point_label, rate in (
                    ("adverse", adverse),
                    ("median", spot),
                    ("favourable", favourable),
                )
            ),
        )
        for ratio, label in ratios
    )

    return HedgeAnalysis(
        optimal_ratio=optimal,
        status=None if optimal is not None else HEDGE_INSUFFICIENT,
        alternatives=() if optimal is not None else INSUFFICIENT_ALTERNATIVES,
        comparison=comparison,
        breakeven=breakeven(
            net_exposure=net_exposure,
            spot_rate=spot_rate,
            baseline_profit=baseline_profit,
            scaled_volatility=scaled_volatility,
        ),
        measure_id=measure.measure_id,
        adverse_rate=_rate(adverse),
        confidence_level=1.0 - alpha,
        z_score=z,
        scaled_volatility=scaled_volatility,
        rate_rounding=ROUNDING,
        profit_rounding=ROUNDING,
    )


def breakeven(
    *,
    net_exposure: Decimal,
    spot_rate: Decimal,
    baseline_profit: Decimal,
    scaled_volatility: float,
) -> BreakevenAnalysis:
    """The unhedged rate at which profit reaches zero, and its probability.

    For a net payer the loss lies above the breakeven rather than below, so the
    probability is taken from the other tail.
    """
    if net_exposure == 0:
        raise ExposureDirectionError(
            "a breakeven rate is undefined for zero net exposure"
        )

    exposure = float(net_exposure)
    spot = float(spot_rate)
    rate = spot - float(baseline_profit) / exposure

    if rate <= 0:
        # No positive rate turns this position negative.
        return BreakevenAnalysis(rate=None, loss_probability=0.0)
    if scaled_volatility <= 0:
        return BreakevenAnalysis(
            rate=_rate(rate),
            loss_probability=0.0 if _profit_is_safe(exposure, spot, rate) else 1.0,
        )

    standardized = math.log(rate / spot) / scaled_volatility
    below = NormalDist().cdf(standardized)
    probability = below if exposure > 0 else 1.0 - below
    return BreakevenAnalysis(rate=_rate(rate), loss_probability=probability)


def _profit_is_safe(exposure: float, spot: float, breakeven_rate: float) -> bool:
    """Whether the spot sits on the profitable side of the breakeven."""
    return spot > breakeven_rate if exposure > 0 else spot < breakeven_rate


def usable_ratio_bounds() -> tuple[float, float]:
    """The hard constraint the optimizer never leaves (§5.3)."""
    return (0.0, 1.0)


def assert_within_bounds(ratios: Iterable[float]) -> None:
    """Reject any ratio outside [0, 1] before it reaches a payoff."""
    low, high = usable_ratio_bounds()
    for ratio in ratios:
        if not low <= ratio <= high:
            raise ValueError(
                f"hedge ratio {ratio} leaves [{low}, {high}]; hedging beyond the "
                "exposure is a new speculative position, not less risk"
            )
