"""Snapshot identity and freshness.

These live in `domain` because both the calculation tools and the knowledge
rules need them, and ADR-0001 lets neither reach into the other's layer.
Everything here is a value object or a pure decision; acquiring a snapshot is
the job of the `integration` leaf module (ADR-0003).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from tradeflow.domain.enums import Freshness


def require_aware(value: datetime, field: str) -> datetime:
    """Reject a timestamp with no time zone.

    Reading a naive timestamp as UTC would be a guess, and a guess about when
    data was observed silently shifts every freshness decision built on it.
    Collectors record an explicit offset instead.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field} must carry a time zone; naive timestamps are not "
            "interpreted on the reader's behalf"
        )
    return value


@dataclass(frozen=True)
class SnapshotRef:
    """Identifies the exact data version a calculation was performed against.

    `observed_at` is when the data describes the world, `retrieved_at` is when
    we fetched it. They differ whenever a source publishes late or serves a
    cached response, and only the first one says whether the data is current.
    """

    source_id: str
    version: str
    observed_at: datetime
    retrieved_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("snapshot version is required for reproducibility")
        if not self.content_hash:
            raise ValueError(
                "content_hash is required: without it a past snapshot cannot be "
                "shown to be the one a past result used"
            )
        object.__setattr__(
            self, "observed_at", require_aware(self.observed_at, "observed_at")
        )
        object.__setattr__(
            self, "retrieved_at", require_aware(self.retrieved_at, "retrieved_at")
        )


@dataclass(frozen=True)
class FreshnessPolicy:
    """Freshness SLA for one class of source.

    Both ages are checked. Observation age catches data that was already old
    when we fetched it, which a retrieval-only check would report as fresh.
    """

    max_observation_age: timedelta
    max_retrieval_age: timedelta | None = None

    def evaluate(self, ref: SnapshotRef, as_of: datetime) -> Freshness:
        as_of = require_aware(as_of, "as_of")

        if not self._within(ref.observed_at, as_of, self.max_observation_age):
            return Freshness.STALE
        if self.max_retrieval_age is not None and not self._within(
            ref.retrieved_at, as_of, self.max_retrieval_age
        ):
            return Freshness.STALE
        return Freshness.FRESH

    def is_usable(self, ref: SnapshotRef, as_of: datetime) -> bool:
        return self.evaluate(ref, as_of) is Freshness.FRESH

    @staticmethod
    def _within(moment: datetime, as_of: datetime, limit: timedelta) -> bool:
        age = as_of - moment
        # A moment after the evaluation instant is a clock or data error we must
        # not resolve by picking whichever reading we prefer.
        return timedelta(0) <= age <= limit
