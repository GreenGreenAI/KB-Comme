"""Reading a stored FX snapshot into a dated rate series.

Snapshots keep the source's response exactly as it arrived (ADR-0003), so
somebody has to interpret that shape. Interpretation is a calculation concern,
not a collection one — `integration` writes the raw bytes and never looks at
them again, while every consumer of the series reaches it through here.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


class SeriesFormatError(ValueError):
    """Raised when a payload does not hold the series it was expected to."""


def usd_krw_series(payload: dict[str, Any]) -> list[tuple[date, Decimal]]:
    """Read a Bank of Korea ECOS payload into observations, oldest first.

    Rows the source published without a value are dropped rather than carried
    forward: a rate that was not published is absent, not unchanged (§9.2).
    """
    rows = payload.get("row")
    if not isinstance(rows, list):
        raise SeriesFormatError("payload has no 'row' list")

    observations: list[tuple[date, Decimal]] = []
    for row in rows:
        raw = (row.get("DATA_VALUE") or "").strip()
        if not raw:
            continue
        try:
            moment = datetime.strptime(row["TIME"], "%Y%m%d").date()
        except (KeyError, ValueError) as exc:
            raise SeriesFormatError(f"unreadable observation date: {exc}") from None
        observations.append((moment, Decimal(raw)))

    if not observations:
        raise SeriesFormatError("payload holds no usable observations")
    observations.sort(key=lambda item: item[0])
    return observations
