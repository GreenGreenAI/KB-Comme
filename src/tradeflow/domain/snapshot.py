"""Snapshot identity and freshness.

These live in `domain` because both the calculation tools and the knowledge
rules need them, and ADR-0001 lets neither reach into the other's layer.
Everything here is a value object or a pure decision; acquiring a snapshot is
the job of the `integration` leaf module (ADR-0003).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from tradeflow.domain.enums import Freshness


def as_utc(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    Snapshot files and source registries are written by different hands and not
    all of them carry an offset. Assuming UTC keeps comparisons total instead of
    raising deep inside a calculation.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@dataclass(frozen=True)
class SnapshotRef:
    """Identifies the exact data version a calculation was performed against."""

    source_id: str
    version: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("snapshot version is required for reproducibility")
        object.__setattr__(self, "retrieved_at", as_utc(self.retrieved_at))


@dataclass(frozen=True)
class FreshnessPolicy:
    """Freshness SLA for one class of source."""

    max_age: timedelta

    def evaluate(self, ref: SnapshotRef, as_of: datetime) -> Freshness:
        age = as_utc(as_of) - ref.retrieved_at
        if age < timedelta(0):
            # Retrieved after the evaluation instant: a clock or data error we
            # must not resolve by guessing which one is right.
            return Freshness.STALE
        return Freshness.FRESH if age <= self.max_age else Freshness.STALE

    def is_usable(self, ref: SnapshotRef, as_of: datetime) -> bool:
        return self.evaluate(ref, as_of) is Freshness.FRESH
