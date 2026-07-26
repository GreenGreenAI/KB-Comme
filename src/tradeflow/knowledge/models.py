from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from tradeflow.domain.enums import Freshness, RuleType, SourceStatus


class ConditionFailureEffect(StrEnum):
    """How a known failed condition affects an eligibility decision."""

    REJECT = "reject"
    CONDITIONAL = "conditional"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    title: str
    organization: str
    url: str
    official: bool
    retrieved_at: datetime
    effective_from: date | None = None
    effective_to: date | None = None
    content_hash: str | None = None
    verified: bool = False
    published_at: datetime | None = None
    freshness_required: bool = False
    usage_policy_url: str | None = None
    attribution: str | None = None

    def status_on(
        self,
        target_date: date,
        *,
        freshness: Freshness | None = None,
    ) -> SourceStatus:
        """Compose authority, effective period and snapshot freshness.

        Authority and effective-period failures take precedence because fresh
        collection cannot make an unverified, future or expired source valid.
        Freshness is considered only for an otherwise active source.
        """
        if not self.verified:
            return SourceStatus.UNVERIFIED
        if self.effective_from and target_date < self.effective_from:
            return SourceStatus.FUTURE
        if self.effective_to and target_date > self.effective_to:
            return SourceStatus.EXPIRED
        if self.freshness_required and freshness is None:
            return SourceStatus.FRESHNESS_UNKNOWN
        if freshness is Freshness.STALE:
            return SourceStatus.STALE
        return SourceStatus.ACTIVE


@dataclass(frozen=True)
class Condition:
    field: str
    operator: str
    value: Any = None
    description: str = ""
    failure_effect: ConditionFailureEffect = ConditionFailureEffect.REJECT


@dataclass(frozen=True)
class KnowledgeRule:
    rule_id: str
    title: str
    topic: str
    rule_type: RuleType
    conditions: tuple[Condition, ...]
    source_ids: tuple[str, ...]
    effective_from: date | None = None
    effective_to: date | None = None
    required_documents: tuple[str, ...] = ()
    procedure_steps: tuple[str, ...] = ()
    production_ready: bool = False
    source_claim_ids: tuple[str, ...] = ()
    candidate_outcome: dict[str, Any] = field(default_factory=dict)

    def effective_on(self, target_date: date) -> bool:
        return not (
            (self.effective_from and target_date < self.effective_from)
            or (self.effective_to and target_date > self.effective_to)
        )
