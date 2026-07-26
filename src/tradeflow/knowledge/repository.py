from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from tradeflow.domain.enums import DecisionStatus, RuleType, SourceStatus
from tradeflow.domain.models import RuleDecision
from tradeflow.knowledge.conditions import evaluate_condition
from tradeflow.knowledge.models import Condition, KnowledgeRule, SourceRecord


class KnowledgeRepository:
    def __init__(
        self,
        sources: Iterable[SourceRecord] = (),
        rules: Iterable[KnowledgeRule] = (),
    ) -> None:
        self.sources = {source.source_id: source for source in sources}
        self.rules = {rule.rule_id: rule for rule in rules}

    @classmethod
    def from_json(cls, source_path: Path, rule_path: Path) -> "KnowledgeRepository":
        source_data = json.loads(source_path.read_text(encoding="utf-8"))
        rule_data = json.loads(rule_path.read_text(encoding="utf-8"))
        sources = [_parse_source(item) for item in source_data["sources"]]
        rules = [_parse_rule(item) for item in rule_data["rules"]]
        return cls(sources, rules)

    def evaluate(
        self,
        *,
        topic: str,
        facts: dict[str, Any],
        as_of: date,
    ) -> tuple[RuleDecision, ...]:
        decisions: list[RuleDecision] = []
        for rule in self.rules.values():
            if rule.topic != topic or not rule.effective_on(as_of):
                continue

            missing_sources = [sid for sid in rule.source_ids if sid not in self.sources]
            source_statuses = [
                self.sources[sid].status_on(as_of)
                for sid in rule.source_ids
                if sid in self.sources
            ]
            results = [evaluate_condition(condition, facts) for condition in rule.conditions]
            failed = [result for result in results if result.status == "failed"]
            uncertain = [result for result in results if result.status == "uncertain"]
            reasons = [result.reason for result in results]

            if missing_sources or SourceStatus.EXPIRED in source_statuses:
                status = DecisionStatus.SOURCE_EXPIRED
                reasons.append(f"unavailable sources: {', '.join(missing_sources)}")
            elif any(status != SourceStatus.ACTIVE for status in source_statuses):
                status = DecisionStatus.EXPERT_CONFIRMATION_REQUIRED
                reasons.append("source is not verified and active")
            elif failed:
                status = DecisionStatus.NOT_ELIGIBLE
            elif uncertain:
                status = DecisionStatus.INSUFFICIENT_INFORMATION
            elif not rule.production_ready:
                status = DecisionStatus.EXPERT_CONFIRMATION_REQUIRED
                reasons.append("draft rule: official confirmation required")
            else:
                status = DecisionStatus.ELIGIBLE_CANDIDATE

            decisions.append(
                RuleDecision(
                    rule_id=rule.rule_id,
                    title=rule.title,
                    status=status,
                    reasons=tuple(reasons),
                    missing_fields=tuple(
                        result.condition.field for result in uncertain
                    ),
                    source_ids=rule.source_ids,
                )
            )
        return tuple(decisions)

    def procedure_for(self, rule_id: str) -> dict[str, Any] | None:
        rule = self.rules.get(rule_id)
        if not rule:
            return None
        return {
            "rule_id": rule.rule_id,
            "title": rule.title,
            "required_documents": list(rule.required_documents),
            "steps": list(rule.procedure_steps),
            "source_ids": list(rule.source_ids),
        }


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_source(item: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        source_id=item["source_id"],
        title=item["title"],
        organization=item["organization"],
        url=item["url"],
        official=bool(item["official"]),
        retrieved_at=datetime.fromisoformat(item["retrieved_at"]),
        effective_from=_parse_date(item.get("effective_from")),
        effective_to=_parse_date(item.get("effective_to")),
        content_hash=item.get("content_hash"),
        verified=bool(item.get("verified", False)),
    )


def _parse_rule(item: dict[str, Any]) -> KnowledgeRule:
    return KnowledgeRule(
        rule_id=item["rule_id"],
        title=item["title"],
        topic=item["topic"],
        rule_type=RuleType(item["rule_type"]),
        conditions=tuple(Condition(**condition) for condition in item.get("conditions", [])),
        source_ids=tuple(item.get("source_ids", [])),
        effective_from=_parse_date(item.get("effective_from")),
        effective_to=_parse_date(item.get("effective_to")),
        required_documents=tuple(item.get("required_documents", [])),
        procedure_steps=tuple(item.get("procedure_steps", [])),
        production_ready=bool(item.get("production_ready", False)),
    )

