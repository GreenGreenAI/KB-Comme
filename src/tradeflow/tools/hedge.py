"""Guards at the entrance to hedge payoff calculation.

The optimizer decides how much to hedge. It never decides what the company is
allowed to hedge with: that judgement belongs to the knowledge layer, which
reads collateral and credit facts. Offering a forward to a company holding no
collateral is the failure mode ADR-0004 exists to prevent, so the boundary is
enforced here in code rather than left to the caller's discipline.
"""

from collections.abc import Iterable

from tradeflow.domain.models import HedgeInstrument


class UnavailableInstrumentError(ValueError):
    """Raised when an instrument the company cannot use reaches the optimizer."""


def usable_instruments(
    instruments: Iterable[HedgeInstrument],
) -> tuple[HedgeInstrument, ...]:
    """Narrow candidates to the instruments the company may actually use."""
    return tuple(item for item in instruments if item.available)


def excluded_instruments(
    instruments: Iterable[HedgeInstrument],
) -> tuple[HedgeInstrument, ...]:
    """The rejected candidates, kept so the response can say why."""
    return tuple(item for item in instruments if not item.available)


def assert_all_available(instruments: Iterable[HedgeInstrument]) -> None:
    """Fail loudly rather than price an instrument the company cannot access."""
    blocked = excluded_instruments(instruments)
    if blocked:
        detail = ", ".join(
            f"{item.instrument_id}({'; '.join(item.exclusion_reasons)})"
            for item in blocked
        )
        raise UnavailableInstrumentError(
            f"unavailable instruments reached the optimizer: {detail}"
        )
