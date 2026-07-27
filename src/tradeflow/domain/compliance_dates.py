"""Deterministic deadline calculations for regulatory procedures."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def add_calendar_months(value: date, months: int) -> date:
    """Add calendar months, clamping to the target month's last day."""
    if months < 0:
        raise ValueError("months must be non-negative")
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def mutual_account_entry_deadline(basis_date: date) -> date:
    """Return the last day of the 30-day entry window under Article 5-6."""
    return basis_date + timedelta(days=30)


def mutual_account_settlement_deadline(period_end: date) -> date:
    """Return the three-calendar-month deadline under Article 5-7."""
    return add_calendar_months(period_end, 3)


def deadline_breached(
    deadline: date,
    *,
    as_of: date,
    completed_on: date | None = None,
) -> bool:
    """A deadline is breached only after its final allowed date."""
    if completed_on is not None and completed_on > as_of:
        raise ValueError("completed_on cannot be after as_of")
    comparison_date = completed_on if completed_on is not None else as_of
    return comparison_date > deadline
