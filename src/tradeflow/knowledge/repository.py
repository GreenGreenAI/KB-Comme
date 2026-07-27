from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradeflow.domain.enums import DecisionStatus, Freshness, RuleType, SourceStatus
from tradeflow.domain.models import DecisionRequirement, RuleDecision
from tradeflow.knowledge.conditions import evaluate_condition
from tradeflow.knowledge.models import (
    Condition,
    ConditionFailureEffect,
    KnowledgeRule,
    SourceRecord,
)


class KnowledgeRepository:
    def __init__(
        self,
        sources: Iterable[SourceRecord] = (),
        rules: Iterable[KnowledgeRule] = (),
    ) -> None:
        sources = tuple(sources)
        rules = tuple(rules)
        self.sources = {source.source_id: source for source in sources}
        self.rules = {rule.rule_id: rule for rule in rules}
        if len(self.sources) != len(sources):
            raise ValueError("knowledge sources contain duplicate source_id values")
        if len(self.rules) != len(rules):
            raise ValueError("knowledge rules contain duplicate rule_id values")

    @classmethod
    def from_json(cls, source_path: Path, rule_path: Path) -> "KnowledgeRepository":
        return cls.from_json_files(source_path, (rule_path,))

    @classmethod
    def from_json_files(
        cls,
        source_path: Path,
        rule_paths: Iterable[Path],
    ) -> "KnowledgeRepository":
        source_data = json.loads(source_path.read_text(encoding="utf-8"))
        sources = [_parse_source(item) for item in source_data["sources"]]
        rules = [
            _parse_rule(item)
            for path in rule_paths
            for item in json.loads(path.read_text(encoding="utf-8"))["rules"]
        ]
        return cls(sources, rules)

    def evaluate(
        self,
        *,
        topic: str,
        facts: dict[str, Any],
        as_of: date,
        source_freshness: Mapping[str, Freshness] | None = None,
        subject_id: str | None = None,
    ) -> tuple[RuleDecision, ...]:
        freshness_by_source = source_freshness or {}
        decisions: list[RuleDecision] = []
        for rule in self.rules.values():
            if rule.topic != topic or not rule.effective_on(as_of):
                continue

            missing_sources = [sid for sid in rule.source_ids if sid not in self.sources]
            source_statuses = {
                sid: self.sources[sid].status_on(
                    as_of,
                    freshness=freshness_by_source.get(sid),
                )
                for sid in rule.source_ids
                if sid in self.sources
            }
            results = [evaluate_condition(condition, facts) for condition in rule.conditions]
            failed = [result for result in results if result.status == "failed"]
            uncertain = [result for result in results if result.status == "uncertain"]
            rejected = [
                result
                for result in failed
                if result.condition.failure_effect is ConditionFailureEffect.REJECT
            ]
            conditional = [
                result
                for result in failed
                if result.condition.failure_effect is ConditionFailureEffect.CONDITIONAL
            ]
            reasons = [result.reason for result in results]
            matched = False if rejected else None if uncertain else True

            if missing_sources:
                status = DecisionStatus.EXPERT_CONFIRMATION_REQUIRED
                reasons.append(f"unavailable sources: {', '.join(missing_sources)}")
            elif SourceStatus.EXPIRED in source_statuses.values():
                status = DecisionStatus.SOURCE_EXPIRED
                reasons.append(_source_status_reason(source_statuses))
            elif any(
                source_status is not SourceStatus.ACTIVE
                for source_status in source_statuses.values()
            ):
                status = DecisionStatus.EXPERT_CONFIRMATION_REQUIRED
                reasons.append(_source_status_reason(source_statuses))
            elif rejected:
                status = DecisionStatus.NOT_ELIGIBLE
            elif uncertain:
                status = DecisionStatus.INSUFFICIENT_INFORMATION
            elif conditional:
                status = DecisionStatus.CONDITIONALLY_ELIGIBLE
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
                    requirements=tuple(
                        DecisionRequirement(
                            field=result.condition.field,
                            operator=result.condition.operator,
                            expected_value=result.condition.value,
                            description=result.condition.description,
                            current_value=facts.get(result.condition.field),
                        )
                        for result in conditional
                        if status is DecisionStatus.CONDITIONALLY_ELIGIBLE
                    ),
                    source_claim_ids=rule.source_claim_ids,
                    candidate_outcome=rule.candidate_outcome,
                    subject_id=subject_id,
                    matched=matched,
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
            "source_claim_ids": list(rule.source_claim_ids),
            "candidate_outcome": dict(rule.candidate_outcome),
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
        published_at=(
            datetime.fromisoformat(item["published_at"])
            if item.get("published_at")
            else None
        ),
        freshness_required=bool(item.get("freshness_required", False)),
        usage_policy_url=item.get("usage_policy_url"),
        attribution=item.get("attribution"),
    )


def _parse_rule(item: dict[str, Any]) -> KnowledgeRule:
    return KnowledgeRule(
        rule_id=item["rule_id"],
        title=item["title"],
        topic=item["topic"],
        rule_type=RuleType(item["rule_type"]),
        conditions=tuple(
            Condition(
                field=condition["field"],
                operator=condition["operator"],
                value=condition.get("value"),
                description=condition.get("description", ""),
                failure_effect=ConditionFailureEffect(
                    condition.get("failure_effect", ConditionFailureEffect.REJECT)
                ),
            )
            for condition in item.get("conditions", [])
        ),
        source_ids=tuple(item.get("source_ids", [])),
        effective_from=_parse_date(item.get("effective_from")),
        effective_to=_parse_date(item.get("effective_to")),
        required_documents=tuple(item.get("required_documents", [])),
        procedure_steps=tuple(item.get("procedure_steps", [])),
        production_ready=bool(item.get("production_ready", False)),
        source_claim_ids=tuple(item.get("source_claim_ids", [])),
        candidate_outcome=dict(item.get("candidate_outcome", {})),
    )


def _source_status_reason(statuses: Mapping[str, SourceStatus]) -> str:
    details = ", ".join(
        f"{source_id}={status.value}"
        for source_id, status in statuses.items()
        if status is not SourceStatus.ACTIVE
    )
    return f"source status: {details}"
