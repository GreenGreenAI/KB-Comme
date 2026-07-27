"""Measuring whether the scenario band covers what actually happened (§5.2).

The product claims it does not predict exchange rates — it states a range and a
confidence level. That claim is only worth something if the range turns out to
hold about as often as it says. This walks the history, builds a band at each
past date using **only data available then**, and checks whether the rate that
actually arrived fell inside it.

Misses are counted per side. One-sided misses would mean the band is centred
wrongly, which is what a zero drift term is supposed to prevent; a bias would
show up here before it showed up in a user's answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence

from tradeflow.tools.volatility import (
    DEFAULT_CONFIDENCE,
    DEFAULT_WINDOW,
    scenario_band,
)

# §5.2 accepts this range as evidence that the band is honestly calibrated.
TARGET_RANGE = (0.85, 0.95)


class InsufficientHistoryError(ValueError):
    """Raised when the series cannot supply a single testable origin."""


@dataclass(frozen=True)
class CoverageResult:
    """How often the band held, and which way it failed when it did not."""

    covered: int
    below: int
    above: int
    horizon_business_days: int
    window: int
    confidence_level: float
    first_origin: date
    last_origin: date

    @property
    def tested(self) -> int:
        return self.covered + self.below + self.above

    @property
    def coverage(self) -> float:
        return self.covered / self.tested

    @property
    def within_target(self) -> bool:
        low, high = TARGET_RANGE
        return low <= self.coverage <= high

    @property
    def miss_balance(self) -> float:
        """Share of misses that fell below the band.

        Near 0.5 means the band missed evenly on both sides. A value near 0 or
        1 means it sat consistently on one side of what happened.
        """
        missed = self.below + self.above
        return self.below / missed if missed else 0.5


def measure_coverage(
    observations: Sequence[tuple[date, Decimal]],
    *,
    horizon_business_days: int,
    window: int = DEFAULT_WINDOW,
    confidence_level: float = DEFAULT_CONFIDENCE,
    step: int = 1,
) -> CoverageResult:
    """Walk the history and count how often the band held.

    Each origin uses the same `scenario_band` the product calls, given only the
    observations up to that origin — no rate from after it reaches the estimate.
    `step` thins overlapping windows; consecutive origins share most of their
    history, so a coarser step trades sample size for independence.
    """
    if step < 1:
        raise ValueError(f"step must be at least 1, got {step}")

    ordered = sorted(observations, key=lambda item: item[0])
    first = window
    last = len(ordered) - horizon_business_days - 1
    if last < first:
        raise InsufficientHistoryError(
            f"a {window}-day window and a {horizon_business_days}-day horizon "
            f"need at least {window + horizon_business_days + 1} observations; "
            f"the series holds {len(ordered)}"
        )

    covered = below = above = 0
    origins: list[date] = []
    for index in range(first, last + 1, step):
        history = ordered[index - window : index + 1]
        band = scenario_band(
            history,
            horizon_business_days=horizon_business_days,
            window=window,
            confidence_level=confidence_level,
        )
        actual = ordered[index + horizon_business_days][1]
        if actual < band.lower:
            below += 1
        elif actual > band.upper:
            above += 1
        else:
            covered += 1
        origins.append(ordered[index][0])

    return CoverageResult(
        covered=covered,
        below=below,
        above=above,
        horizon_business_days=horizon_business_days,
        window=window,
        confidence_level=confidence_level,
        first_origin=origins[0],
        last_origin=origins[-1],
    )
