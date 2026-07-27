"""Realized volatility and the scenario band it implies (§5.2).

The band is centred on the current rate and never anywhere else. Its width
comes from how much the rate has actually moved, not from a view about where
it is heading — introducing a drift term would contradict the product's own
statement that it does not predict exchange rates.

Everything here is a pure function of an observed series. Deciding which window
and which confidence level to ask for belongs to the agent; deciding whether
the underlying snapshot may be used at all is `require_fresh` below.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import NormalDist
from typing import Sequence

from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef

# Korean business days in a year, the convention used to annualize a daily
# figure for display. It scales the reported number only; the band is built
# from the horizon in business days, never from this constant.
BUSINESS_DAYS_PER_YEAR = 252

DEFAULT_WINDOW = 60
DEFAULT_CONFIDENCE = 0.90

# ECOS quotes the reference rate to one decimal place. Band bounds come out of
# an exponential, so they are rounded to two and the mode is reported with the
# result (§9.1).
RATE_EXPONENT = Decimal("0.01")
ROUNDING = "ROUND_HALF_UP"


class InsufficientObservationsError(ValueError):
    """Raised when the series is too short for the requested window."""


class StaleSnapshotError(RuntimeError):
    """Raised when a scenario is requested from a snapshot past its SLA."""


def require_fresh(
    ref: SnapshotRef, policy: FreshnessPolicy, as_of: datetime
) -> None:
    """Refuse to build a scenario on data the policy considers stale.

    §4.2[4] makes staleness the market worker's stopping condition, so the
    check lives at the tool boundary rather than in the caller's discipline.
    """
    if policy.evaluate(ref, as_of) is not Freshness.FRESH:
        raise StaleSnapshotError(
            f"{ref.source_id} {ref.version} observed at {ref.observed_at} is "
            f"stale as of {as_of}; a band must not be built on it"
        )


@dataclass(frozen=True)
class VolatilityEstimate:
    """Realized volatility over a closed window of observations."""

    daily: float
    annualized: float
    window: int
    first_observed: date
    last_observed: date


@dataclass(frozen=True)
class ScenarioBand:
    """A quantile band for one horizon, with the basis needed to read it."""

    spot_rate: Decimal
    lower: Decimal
    upper: Decimal
    confidence_level: float
    z_score: float
    horizon_business_days: int
    scaled_volatility: float
    volatility: VolatilityEstimate
    unit: str
    rounding: str


def _ordered(observations: Sequence[tuple[date, Decimal]]) -> list[tuple[date, Decimal]]:
    ordered = sorted(observations, key=lambda item: item[0])
    seen: set[date] = set()
    for moment, rate in ordered:
        if moment in seen:
            raise ValueError(f"duplicate observation for {moment.isoformat()}")
        if rate <= 0:
            raise ValueError(f"non-positive rate {rate} on {moment.isoformat()}")
        seen.add(moment)
    return ordered


def log_returns(observations: Sequence[tuple[date, Decimal]]) -> list[float]:
    """Daily log returns between consecutive observations.

    Consecutive means consecutive *in the series*: a market holiday leaves no
    observation, and the return spans the gap rather than being invented for it.
    """
    ordered = _ordered(observations)
    return [
        math.log(float(ordered[i][1]) / float(ordered[i - 1][1]))
        for i in range(1, len(ordered))
    ]


def estimate_volatility(
    observations: Sequence[tuple[date, Decimal]],
    window: int = DEFAULT_WINDOW,
) -> VolatilityEstimate:
    """Estimate daily volatility from the most recent `window` returns.

    `window` counts returns, so it needs `window + 1` observations. A shorter
    series raises instead of quietly estimating on fewer days: the window is
    reported with the result, and silently changing it would make that report
    wrong (§9.2).
    """
    if window < 2:
        raise ValueError(f"window must cover at least 2 returns, got {window}")

    ordered = _ordered(observations)
    available = len(ordered) - 1
    if available < window:
        raise InsufficientObservationsError(
            f"window of {window} returns needs {window + 1} observations; "
            f"the series holds {len(ordered)}"
        )

    used = ordered[-(window + 1) :]
    returns = log_returns(used)
    daily = statistics.stdev(returns)
    return VolatilityEstimate(
        daily=daily,
        annualized=daily * math.sqrt(BUSINESS_DAYS_PER_YEAR),
        window=window,
        first_observed=used[0][0],
        last_observed=used[-1][0],
    )


def z_for(confidence_level: float) -> float:
    """Two-sided z-score for a confidence level.

    Reproduces the values §5.2 tabulates (0.90 → 1.645, 0.95 → 1.96) without
    restricting the caller to those two.
    """
    if not 0 < confidence_level < 1:
        raise ValueError(
            f"confidence_level must sit strictly between 0 and 1, "
            f"got {confidence_level}"
        )
    return NormalDist().inv_cdf((1 + confidence_level) / 2)


def _rounded(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(RATE_EXPONENT, rounding=ROUND_HALF_UP)


def scenario_band(
    observations: Sequence[tuple[date, Decimal]],
    *,
    horizon_business_days: int,
    window: int = DEFAULT_WINDOW,
    confidence_level: float = DEFAULT_CONFIDENCE,
    unit: str = "KRW per USD",
) -> ScenarioBand:
    """Build the band the most recent rate implies over a horizon.

    The band is symmetric in log space around the current rate: no drift term
    (§5.2), so the product never states a direction it cannot support.
    """
    if horizon_business_days < 1:
        raise ValueError(
            f"horizon must be at least one business day, "
            f"got {horizon_business_days}"
        )

    ordered = _ordered(observations)
    estimate = estimate_volatility(ordered, window)
    spot = ordered[-1][1]

    scaled = estimate.daily * math.sqrt(horizon_business_days)
    z = z_for(confidence_level)
    spread = math.exp(z * scaled)
    spot_as_float = float(spot)

    return ScenarioBand(
        spot_rate=spot,
        lower=_rounded(spot_as_float / spread),
        upper=_rounded(spot_as_float * spread),
        confidence_level=confidence_level,
        z_score=z,
        horizon_business_days=horizon_business_days,
        scaled_volatility=scaled,
        volatility=estimate,
        unit=unit,
        rounding=ROUNDING,
    )
