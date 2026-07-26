from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from tradeflow.domain.enums import RuleType, SourceStatus


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

    def status_on(self, target_date: date) -> SourceStatus:
        if not self.verified:
            return SourceStatus.UNVERIFIED
        if self.effective_from and target_date < self.effective_from:
            return SourceStatus.FUTURE
        if self.effective_to and target_date > self.effective_to:
            return SourceStatus.EXPIRED
        return SourceStatus.ACTIVE


@dataclass(frozen=True)
class Condition:
    field: str
    operator: str
    value: Any = None
    description: str = ""


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

    def effective_on(self, target_date: date) -> bool:
        return not (
            (self.effective_from and target_date < self.effective_from)
            or (self.effective_to and target_date > self.effective_to)
        )
