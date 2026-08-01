from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradeflow.domain.enums import (
    DecisionCategory,
    DecisionStatus,
    Freshness,
    RuleType,
    SourceStatus,
)
from tradeflow.domain.models import DecisionCheck, DecisionRequirement, RuleDecision
from tradeflow.knowledge.conditions import evaluate_condition
from tradeflow.knowledge.documents import ApplicationDocumentSet, DocumentCatalog
from tradeflow.knowledge.models import (
    Condition,
    ConditionFailureEffect,
    KnowledgeRule,
    ReviewPolicy,
    SourceRecord,
)


class KnowledgeRepository:
    def __init__(
        self,
        sources: Iterable[SourceRecord] = (),
        rules: Iterable[KnowledgeRule] = (),
        document_sets: Iterable[ApplicationDocumentSet] = (),
    ) -> None:
        sources = tuple(sources)
        rules = tuple(rules)
        document_sets = tuple(document_sets)
        self.sources = {source.source_id: source for source in sources}
        self.rules = {rule.rule_id: rule for rule in rules}
        self.document_sets = {
            item.document_set_id: item for item in document_sets
        }
        if len(self.sources) != len(sources):
            raise ValueError("knowledge sources contain duplicate source_id values")
        if len(self.rules) != len(rules):
            raise ValueError("knowledge rules contain duplicate rule_id values")
        if len(self.document_sets) != len(document_sets):
            raise ValueError("knowledge contains duplicate document_set_id values")
        for rule in rules:
            if rule.required_documents and rule.document_set_ids:
                raise ValueError(
                    f"{rule.rule_id}: use inline required_documents or "
                    "document_set_ids, not both"
                )
            for document_set_id in rule.document_set_ids:
                if document_set_id not in self.document_sets:
                    raise ValueError(
                        f"{rule.rule_id}: unknown document_set_id "
                        f"{document_set_id}"
                    )
                document_set = self.document_sets[document_set_id]
                product_id = rule.candidate_outcome.get("product_id")
                if product_id != document_set.product_id:
                    raise ValueError(
                        f"{rule.rule_id}: product_id does not match "
                        f"{document_set_id}"
                    )

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
        rules: list[KnowledgeRule] = []
        document_sets: list[ApplicationDocumentSet] = []
        loaded_catalogs: set[Path] = set()
        for path in rule_paths:
            rule_data = json.loads(path.read_text(encoding="utf-8"))
            rules.extend(_parse_rule(item) for item in rule_data["rules"])
            for relative_path in rule_data.get("document_catalogs", []):
                catalog_path = (path.parent / relative_path).resolve()
                if catalog_path in loaded_catalogs:
                    continue
                loaded_catalogs.add(catalog_path)
                document_sets.extend(
                    DocumentCatalog.from_json(catalog_path).document_sets.values()
                )
        return cls(sources, rules, document_sets)

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

            document_sets = tuple(
                self.document_sets[item] for item in rule.document_set_ids
            )
            source_ids = tuple(
                dict.fromkeys(
                    (
                        *rule.source_ids,
                        *(
                            source_id
                            for document_set in document_sets
                            for source_id in document_set.source_ids
                        ),
                    )
                )
            )
            source_claim_ids = tuple(
                dict.fromkeys(
                    (
                        *rule.source_claim_ids,
                        *(
                            claim_id
                            for document_set in document_sets
                            for claim_id in document_set.source_claim_ids
                        ),
                    )
                )
            )
            missing_sources = [sid for sid in source_ids if sid not in self.sources]
            source_statuses = {
                sid: self.sources[sid].status_on(
                    as_of,
                    freshness=freshness_by_source.get(sid),
                )
                for sid in source_ids
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
            elif rule.review_policy is ReviewPolicy.ALWAYS_EXPERT:
                status = DecisionStatus.EXPERT_CONFIRMATION_REQUIRED
                reasons.append("rule policy requires expert confirmation")
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
                    source_ids=source_ids,
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
                    # Every condition in the words the rulepack wrote it in.
                    # Separate from `requirements`, which means something
                    # narrower — the remediable conditions blocking a
                    # conditional eligibility — and is tested for meaning that.
                    #
                    # Without this the answer could only show the comparison
                    # that produced a verdict: `company.size=small in
                    # ['small', 'mid_sized']`. The Korean was written once, by
                    # the person who wrote the rule, and dropped one layer
                    # later.
                    checks=tuple(
                        DecisionCheck(
                            field=result.condition.field,
                            description=result.condition.description,
                            status=result.status,
                        )
                        for result in results
                        if result.condition.description
                    ),
                    source_claim_ids=source_claim_ids,
                    candidate_outcome=rule.candidate_outcome,
                    subject_id=subject_id,
                    matched=matched,
                    categories=_decision_categories(
                        status=status,
                        matched=matched,
                        candidate_outcome=rule.candidate_outcome,
                    ),
                )
            )
        return tuple(decisions)

    def procedure_for(self, rule_id: str) -> dict[str, Any] | None:
        rule = self.rules.get(rule_id)
        if not rule:
            return None
        document_sets = tuple(
            self.document_sets[item] for item in rule.document_set_ids
        )
        return {
            "rule_id": rule.rule_id,
            "title": rule.title,
            "required_documents": list(
                dict.fromkeys(
                    (
                        *rule.required_documents,
                        *(
                            title
                            for document_set in document_sets
                            for title in document_set.universally_required_titles
                        ),
                    )
                )
            ),
            "document_set_ids": list(rule.document_set_ids),
            "document_requirements": [
                requirement
                for document_set in document_sets
                for requirement in document_set.requirements
            ],
            "steps": list(rule.procedure_steps),
            "source_ids": list(
                dict.fromkeys(
                    (
                        *rule.source_ids,
                        *(
                            source_id
                            for document_set in document_sets
                            for source_id in document_set.source_ids
                        ),
                    )
                )
            ),
            "source_claim_ids": list(
                dict.fromkeys(
                    (
                        *rule.source_claim_ids,
                        *(
                            claim_id
                            for document_set in document_sets
                            for claim_id in document_set.source_claim_ids
                        ),
                    )
                )
            ),
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
        official=_strict_bool(item, "official"),
        retrieved_at=datetime.fromisoformat(item["retrieved_at"]),
        effective_from=_parse_date(item.get("effective_from")),
        effective_to=_parse_date(item.get("effective_to")),
        content_hash=item.get("content_hash"),
        verified=_strict_bool(item, "verified", default=False),
        published_at=(
            datetime.fromisoformat(item["published_at"])
            if item.get("published_at")
            else None
        ),
        freshness_required=_strict_bool(
            item,
            "freshness_required",
            default=False,
        ),
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
        production_ready=_strict_bool(item, "production_ready", default=False),
        source_claim_ids=tuple(item.get("source_claim_ids", [])),
        candidate_outcome=dict(item.get("candidate_outcome", {})),
        document_set_ids=tuple(item.get("document_set_ids", [])),
        review_policy=ReviewPolicy(item.get("review_policy", ReviewPolicy.AUTOMATIC)),
    )


def _strict_bool(
    item: Mapping[str, Any],
    field: str,
    *,
    default: bool | None = None,
) -> bool:
    value = item.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _source_status_reason(statuses: Mapping[str, SourceStatus]) -> str:
    details = ", ".join(
        f"{source_id}={status.value}"
        for source_id, status in statuses.items()
        if status is not SourceStatus.ACTIVE
    )
    return f"source status: {details}"


def _decision_categories(
    *,
    status: DecisionStatus,
    matched: bool | None,
    candidate_outcome: Mapping[str, Any],
) -> tuple[DecisionCategory, ...]:
    categories: list[DecisionCategory] = []
    if matched is True:
        categories.append(DecisionCategory.CANDIDATE)
    elif matched is False:
        categories.append(DecisionCategory.EXCLUDED)
    else:
        categories.append(DecisionCategory.MISSING_INFORMATION)

    if status is DecisionStatus.INSUFFICIENT_INFORMATION:
        categories.append(DecisionCategory.MISSING_INFORMATION)
    elif status is DecisionStatus.EXPERT_CONFIRMATION_REQUIRED:
        categories.append(DecisionCategory.EXPERT_REVIEW)
    elif status is DecisionStatus.SOURCE_EXPIRED:
        categories.append(DecisionCategory.SOURCE_UNUSABLE)
    elif status is DecisionStatus.NOT_ELIGIBLE:
        categories.append(DecisionCategory.EXCLUDED)

    if matched is True and candidate_outcome.get("timing") == "immediate":
        categories.append(DecisionCategory.URGENT_ACTION)
    return tuple(dict.fromkeys(categories))
