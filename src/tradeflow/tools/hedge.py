"""Guards for the entrance to hedge payoff calculation.

The optimizer decides how much to hedge. It never decides what the company is
allowed to hedge with: that judgement belongs to the knowledge layer, which
reads collateral and credit facts. Offering a forward to a company holding no
collateral is the failure mode ADR-0004 exists to prevent.

These are the guards the optimizer will sit behind. The optimizer itself is not
built yet, so nothing calls `assert_all_usable` in the running pipeline; wiring
it to the §5.3 entry point is what completes the enforcement.
"""

from collections.abc import Iterable

from tradeflow.domain.enums import AvailabilityStatus
from tradeflow.domain.models import HedgeMeasure


# Anything other than AVAILABLE stays out of the payoff calculation. A measure
# that is conditional or undetermined is not a cheaper AVAILABLE: pricing it
# would present an unsettled question as a settled number.
REVIEW_STATUSES = frozenset(
    {
        AvailabilityStatus.CONDITIONAL,
        AvailabilityStatus.INSUFFICIENT_INFORMATION,
        AvailabilityStatus.EXPERT_CONFIRMATION_REQUIRED,
    }
)


class UnusableMeasureError(ValueError):
    """Raised when a measure that is not AVAILABLE reaches the optimizer."""


def usable_measures(measures: Iterable[HedgeMeasure]) -> tuple[HedgeMeasure, ...]:
    """Narrow candidates to the measures the company may actually use."""
    return tuple(
        item for item in measures if item.status is AvailabilityStatus.AVAILABLE
    )


def unavailable_measures(measures: Iterable[HedgeMeasure]) -> tuple[HedgeMeasure, ...]:
    """Measures ruled out, kept so the response can say why."""
    return tuple(
        item for item in measures if item.status is AvailabilityStatus.UNAVAILABLE
    )


def review_measures(measures: Iterable[HedgeMeasure]) -> tuple[HedgeMeasure, ...]:
    """Measures whose availability is unsettled.

    These feed `review_required` rather than the payoff comparison, so an open
    question reaches a person instead of being resolved by omission.
    """
    return tuple(item for item in measures if item.status in REVIEW_STATUSES)


def assert_all_usable(measures: Iterable[HedgeMeasure]) -> None:
    """Fail loudly rather than price a measure the company cannot access."""
    blocked = tuple(
        item for item in measures if item.status is not AvailabilityStatus.AVAILABLE
    )
    if blocked:
        detail = ", ".join(
            f"{item.measure_id}[{item.status.value}]"
            f"({'; '.join(item.status_reasons)})"
            for item in blocked
        )
        raise UnusableMeasureError(
            f"measures that are not available reached the optimizer: {detail}"
        )
