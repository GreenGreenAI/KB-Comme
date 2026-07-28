from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.domain.enums import DecisionStatus, Freshness
from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.knowledge.conditions import evaluate_condition
from tradeflow.knowledge.facts import FactCatalog, FactContractError


@dataclass(frozen=True)
class ExpectedDecision:
    rule_id: str
    matched: bool | None
    status: DecisionStatus
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleValidationCase:
    case_id: str
    topic: str
    facts: Mapping[str, Any]
    expectations: tuple[ExpectedDecision, ...]


@dataclass(frozen=True)
class BoundarySample:
    value: Any
    passed: bool


@dataclass(frozen=True)
class NumericBoundaryCheck:
    rule_id: str
    field: str
    operator: str
    expected_threshold: Decimal
    samples: tuple[BoundarySample, ...]


@dataclass(frozen=True)
class RuleValidationSuite:
    suite_id: str
    pack_id: str
    as_of: date
    cases: tuple[RuleValidationCase, ...]
    boundary_checks: tuple[NumericBoundaryCheck, ...]

    @classmethod
    def from_json(cls, path: Path) -> "RuleValidationSuite":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            raise ValueError(f"{path}: unsupported validation suite schema_version")
        cases = tuple(_parse_case(item) for item in payload.get("cases", []))
        if not cases:
            raise ValueError(f"{path}: validation suite cases must not be empty")
        case_ids = [item.case_id for item in cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError(f"{path}: duplicate validation case_id")
        return cls(
            suite_id=_required_string(payload, "suite_id"),
            pack_id=_required_string(payload, "pack_id"),
            as_of=date.fromisoformat(_required_string(payload, "as_of")),
            cases=cases,
            boundary_checks=tuple(
                _parse_boundary_check(item)
                for item in payload.get("boundary_checks", [])
            ),
        )


@dataclass(frozen=True)
class ValidationReport:
    suite_id: str
    case_count: int
    boundary_count: int
    rule_count: int
    issues: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.issues


def validate_rule_suite(
    suite: RuleValidationSuite,
    repository: KnowledgeRepository,
    fact_catalog: FactCatalog | None = None,
) -> ValidationReport:
    """Evaluate declared outcomes and require true/false/missing coverage per rule."""
    issues: list[str] = []
    coverage: dict[str, set[bool | None]] = {
        rule_id: set() for rule_id in repository.rules
    }
    freshness = {
        source_id: Freshness.FRESH for source_id in repository.sources
    }

    for case in suite.cases:
        facts = dict(case.facts)
        if fact_catalog is not None:
            normalized: dict[str, Any] = {}
            for field, value in facts.items():
                try:
                    normalized[field] = fact_catalog.normalize(field, value)
                except FactContractError as exc:
                    issues.append(f"{case.case_id}: invalid golden fact: {exc}")
            facts = normalized
        decisions = {
            item.rule_id: item
            for item in repository.evaluate(
                topic=case.topic,
                facts=facts,
                as_of=suite.as_of,
                source_freshness=freshness,
            )
        }
        expected_ids: set[str] = set()
        for expected in case.expectations:
            if expected.rule_id in expected_ids:
                issues.append(
                    f"{case.case_id}: duplicate expectation {expected.rule_id}"
                )
                continue
            expected_ids.add(expected.rule_id)
            if expected.rule_id not in repository.rules:
                issues.append(
                    f"{case.case_id}: unknown rule {expected.rule_id}"
                )
                continue
            decision = decisions.get(expected.rule_id)
            if decision is None:
                issues.append(
                    f"{case.case_id}: rule did not evaluate {expected.rule_id}"
                )
                continue
            coverage[expected.rule_id].add(expected.matched)
            if decision.matched is not expected.matched:
                issues.append(
                    f"{case.case_id}/{expected.rule_id}: matched "
                    f"{decision.matched!r} != {expected.matched!r}"
                )
            if decision.status is not expected.status:
                issues.append(
                    f"{case.case_id}/{expected.rule_id}: status "
                    f"{decision.status.value} != {expected.status.value}"
                )
            if decision.missing_fields != expected.missing_fields:
                issues.append(
                    f"{case.case_id}/{expected.rule_id}: missing_fields "
                    f"{decision.missing_fields!r} != {expected.missing_fields!r}"
                )

    required = {True, False, None}
    for rule_id, covered in coverage.items():
        missing = required - covered
        if missing:
            labels = sorted("missing" if item is None else str(item).lower() for item in missing)
            issues.append(
                f"{rule_id}: missing golden coverage for {', '.join(labels)}"
            )
    issues.extend(_validate_boundary_checks(suite, repository, fact_catalog))
    return ValidationReport(
        suite_id=suite.suite_id,
        case_count=len(suite.cases),
        boundary_count=len(suite.boundary_checks),
        rule_count=len(repository.rules),
        issues=tuple(issues),
    )


@dataclass(frozen=True)
class PromotionApproval:
    role: str
    status: str
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    commit_sha: str | None = None
    rulepack_hash: str | None = None
    validation_suite_hash: str | None = None
    reviewer_organization: str | None = None
    authority_basis: str | None = None
    evidence_content_hash: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"{self.role}: unsupported approval status")
        fields = (
            self.reviewer,
            self.reviewed_at,
            self.commit_sha,
            self.rulepack_hash,
            self.validation_suite_hash,
        )
        if self.status in {"approved", "rejected"} and not all(fields):
            raise ValueError(
                f"{self.role}: reviewed decision needs reviewer, time, commit and hashes"
            )
        expert_fields = (
            self.reviewer_organization,
            self.authority_basis,
            self.evidence_content_hash,
        )
        if self.status == "pending" and any(
            item is not None for item in (*fields, *expert_fields)
        ):
            raise ValueError(f"{self.role}: pending review must not claim review metadata")
        if (
            self.role == "domain_expert"
            and self.status in {"approved", "rejected"}
            and not all(expert_fields)
        ):
            raise ValueError(
                "domain_expert: reviewed decision needs organization, "
                "authority basis and evidence hash"
            )
        if self.reviewed_at and self.reviewed_at.utcoffset() is None:
            raise ValueError(f"{self.role}: reviewed_at must include a UTC offset")
        if self.commit_sha and not re.fullmatch(r"[0-9a-f]{7,40}", self.commit_sha):
            raise ValueError(f"{self.role}: commit_sha must be a Git hex object ID")
        for label, value in (
            ("rulepack_hash", self.rulepack_hash),
            ("validation_suite_hash", self.validation_suite_hash),
            ("evidence_content_hash", self.evidence_content_hash),
        ):
            if value and not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                raise ValueError(f"{self.role}: {label} must be canonical SHA-256")


@dataclass(frozen=True)
class RulepackPromotionSpec:
    pack_id: str
    rulepack_path: Path
    validation_suite_path: Path
    required_roles: tuple[str, ...]
    approvals: tuple[PromotionApproval, ...]


@dataclass(frozen=True)
class RulepackReadiness:
    pack_id: str
    validation: ValidationReport
    blockers: tuple[str, ...]
    integrity_issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers and not self.integrity_issues


def load_promotion_manifest(
    project_root: Path,
    manifest_path: Path,
) -> tuple[RulepackPromotionSpec, ...]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported promotion manifest schema_version")
    specs = tuple(
        _parse_promotion_spec(project_root, item)
        for item in payload.get("rulepacks", [])
    )
    pack_ids = [item.pack_id for item in specs]
    if not specs or len(set(pack_ids)) != len(pack_ids):
        raise ValueError("promotion manifest needs unique rulepack entries")
    policy_roles = tuple(payload.get("policy", {}).get("required_roles", []))
    if not policy_roles or len(set(policy_roles)) != len(policy_roles):
        raise ValueError("promotion policy required_roles must be unique and non-empty")
    for spec in specs:
        if set(spec.required_roles) != set(policy_roles):
            raise ValueError(f"{spec.pack_id}: required_roles differ from policy")
    return specs


def audit_rulepack_readiness(
    *,
    project_root: Path,
    source_registry_path: Path,
    spec: RulepackPromotionSpec,
) -> RulepackReadiness:
    raw_pack = json.loads(spec.rulepack_path.read_text(encoding="utf-8"))
    raw_suite = json.loads(spec.validation_suite_path.read_text(encoding="utf-8"))
    suite = RuleValidationSuite.from_json(spec.validation_suite_path)
    repository = KnowledgeRepository.from_json(
        source_registry_path,
        spec.rulepack_path,
    )
    validation = validate_rule_suite(
        suite,
        repository,
        FactCatalog.from_json(project_root / "knowledge" / "fact_catalog.json"),
    )
    issues = list(validation.issues)
    blockers: list[str] = []

    if raw_pack.get("pack_id") != spec.pack_id:
        issues.append(f"{spec.pack_id}: manifest and rulepack pack_id differ")
    if suite.pack_id != spec.pack_id:
        issues.append(f"{spec.pack_id}: suite and manifest pack_id differ")

    raw_rules = raw_pack.get("rules", [])
    if not isinstance(raw_rules, list) or not raw_rules:
        issues.append(f"{spec.pack_id}: rules must be a non-empty list")
        raw_rules = []
    for raw_rule in raw_rules:
        rule_id = raw_rule.get("rule_id", "<unknown>")
        if not isinstance(raw_rule.get("production_ready"), bool):
            issues.append(f"{rule_id}: production_ready must be boolean")
        if "review_policy" not in raw_rule:
            issues.append(f"{rule_id}: review_policy must be explicit")
        rule = repository.rules.get(rule_id)
        if rule is None:
            continue
        procedure = repository.procedure_for(rule_id)
        outcome = procedure["candidate_outcome"]
        for field in ("kind", "authority", "action", "timing"):
            if not isinstance(outcome.get(field), str) or not outcome[field]:
                issues.append(f"{rule_id}: candidate {field} must be explicit")
        if not rule.source_claim_ids:
            issues.append(f"{rule_id}: source_claim_ids must not be empty")
        if not procedure["steps"]:
            issues.append(f"{rule_id}: procedure steps must not be empty")
        if not (
            procedure["required_documents"]
            or procedure["document_requirements"]
        ):
            issues.append(f"{rule_id}: document requirements must not be empty")

    approval_by_role = {item.role: item for item in spec.approvals}
    if len(approval_by_role) != len(spec.approvals):
        issues.append(f"{spec.pack_id}: duplicate approval role")
    if set(approval_by_role) != set(spec.required_roles):
        issues.append(f"{spec.pack_id}: approvals must exactly match required_roles")
    for role in spec.required_roles:
        approval = approval_by_role.get(role)
        if approval is None or approval.status == "pending":
            blockers.append(f"pending approval: {role}")
            continue
        if approval.status == "rejected":
            blockers.append(f"rejected approval: {role}")
            continue
        if approval.rulepack_hash != content_hash(raw_pack):
            issues.append(f"{spec.pack_id}: {role} approval rulepack hash is stale")
        if approval.validation_suite_hash != content_hash(raw_suite):
            issues.append(f"{spec.pack_id}: {role} approval validation hash is stale")
    domain_approval = approval_by_role.get("domain_expert")
    author_approval = approval_by_role.get("knowledge_domain")
    if (
        domain_approval
        and domain_approval.status in {"approved", "rejected"}
        and author_approval
        and author_approval.reviewer
        and domain_approval.reviewer == author_approval.reviewer
    ):
        issues.append(
            f"{spec.pack_id}: domain expert must be independent from rule author"
        )

    referenced_sources = {
        source_id
        for rule in repository.rules.values()
        for source_id in repository.procedure_for(rule.rule_id)["source_ids"]
    }
    for source_id in sorted(referenced_sources):
        source = repository.sources.get(source_id)
        if source is None:
            issues.append(f"{spec.pack_id}: missing source {source_id}")
        elif not (
            source.official
            and source.verified
            and source.content_hash
            and re.fullmatch(r"sha256:[0-9a-f]{64}", source.content_hash)
        ):
            issues.append(f"{spec.pack_id}: source is not promotion-safe {source_id}")

    pack_status = raw_pack.get("status")
    if pack_status not in {"draft", "active"}:
        issues.append(f"{spec.pack_id}: unsupported rulepack status {pack_status!r}")
    if raw_pack.get("as_of") != suite.as_of.isoformat():
        issues.append(f"{spec.pack_id}: rulepack and suite as_of differ")
    any_production = any(rule.production_ready for rule in repository.rules.values())
    all_production = all(rule.production_ready for rule in repository.rules.values())
    pack_active = pack_status == "active"
    approvals_complete = not blockers
    if any_production != all_production:
        issues.append(f"{spec.pack_id}: partial production_ready state is forbidden")
    if all_production != pack_active:
        issues.append(f"{spec.pack_id}: rule and pack production states differ")
    if (any_production or pack_active) and (
        issues or not approvals_complete or not validation.passed
    ):
        issues.append(
            f"{spec.pack_id}: production state is forbidden while gates are incomplete"
        )
    if not all_production:
        blockers.append("rules remain production_ready=false")
    if not pack_active:
        blockers.append("rulepack status is not active")

    return RulepackReadiness(
        pack_id=spec.pack_id,
        validation=validation,
        blockers=tuple(dict.fromkeys(blockers)),
        integrity_issues=tuple(dict.fromkeys(issues)),
    )


def _parse_case(item: dict[str, Any]) -> RuleValidationCase:
    facts = item.get("facts")
    if not isinstance(facts, dict):
        raise ValueError("validation case facts must be an object")
    expectations_list: list[ExpectedDecision] = []
    for expected in item.get("expectations", []):
        if "matched" not in expected:
            raise ValueError("expected matched must be explicit")
        matched = expected.get("matched")
        if matched is not None and not isinstance(matched, bool):
            raise ValueError("expected matched must be true, false or null")
        expectations_list.append(
            ExpectedDecision(
                rule_id=_required_string(expected, "rule_id"),
                matched=matched,
                status=DecisionStatus(_required_string(expected, "status")),
                missing_fields=tuple(expected.get("missing_fields", [])),
            )
        )
    expectations = tuple(expectations_list)
    if not expectations:
        raise ValueError("validation case expectations must not be empty")
    return RuleValidationCase(
        case_id=_required_string(item, "case_id"),
        topic=_required_string(item, "topic"),
        facts=MappingProxyType(dict(facts)),
        expectations=expectations,
    )


def _parse_boundary_check(item: dict[str, Any]) -> NumericBoundaryCheck:
    samples: list[BoundarySample] = []
    for sample in item.get("samples", []):
        if not isinstance(sample.get("passed"), bool):
            raise ValueError("boundary sample passed must be boolean")
        samples.append(BoundarySample(sample.get("value"), sample["passed"]))
    if not samples:
        raise ValueError("boundary check samples must not be empty")
    try:
        threshold = Decimal(_required_string(item, "expected_threshold"))
    except InvalidOperation:
        raise ValueError("expected_threshold must be a decimal string") from None
    if not threshold.is_finite():
        raise ValueError("expected_threshold must be finite")
    return NumericBoundaryCheck(
        rule_id=_required_string(item, "rule_id"),
        field=_required_string(item, "field"),
        operator=_required_string(item, "operator"),
        expected_threshold=threshold,
        samples=tuple(samples),
    )


def _validate_boundary_checks(
    suite: RuleValidationSuite,
    repository: KnowledgeRepository,
    fact_catalog: FactCatalog | None,
) -> tuple[str, ...]:
    issues: list[str] = []
    check_by_key: dict[tuple[str, str, str], NumericBoundaryCheck] = {}
    for check in suite.boundary_checks:
        key = (check.rule_id, check.field, check.operator)
        if key in check_by_key:
            issues.append(f"duplicate boundary check: {'/'.join(key)}")
            continue
        check_by_key[key] = check

    required: dict[tuple[str, str, str], Decimal] = {}
    for rule in repository.rules.values():
        for condition in rule.conditions:
            if condition.operator in {"gt", "gte", "lt", "lte"} or (
                condition.operator == "eq"
                and isinstance(condition.value, (int, float))
                and not isinstance(condition.value, bool)
            ):
                required[(rule.rule_id, condition.field, condition.operator)] = (
                    Decimal(str(condition.value))
                )

    for key, threshold in required.items():
        check = check_by_key.get(key)
        label = "/".join(key)
        if check is None:
            issues.append(f"missing numeric boundary check: {label}")
            continue
        if check.expected_threshold != threshold:
            issues.append(
                f"{label}: rule threshold {threshold} != golden "
                f"{check.expected_threshold}"
            )
        relations: set[int] = set()
        rule = repository.rules[key[0]]
        condition = next(
            item
            for item in rule.conditions
            if item.field == key[1] and item.operator == key[2]
        )
        for sample in check.samples:
            try:
                value = Decimal(str(sample.value))
            except InvalidOperation:
                issues.append(f"{label}: boundary sample is not decimal")
                continue
            if not value.is_finite():
                issues.append(f"{label}: boundary sample must be finite")
                continue
            sample_value = sample.value
            if fact_catalog is not None:
                try:
                    sample_value = fact_catalog.normalize(
                        condition.field,
                        sample.value,
                    )
                except FactContractError as exc:
                    issues.append(f"{label}: invalid boundary fact: {exc}")
                    continue
            relations.add((value > threshold) - (value < threshold))
            result = evaluate_condition(condition, {condition.field: sample_value})
            actual = result.status == "passed"
            if actual is not sample.passed:
                issues.append(
                    f"{label}: sample {sample.value!r} pass={actual} "
                    f"!= {sample.passed}"
                )
        if relations != {-1, 0, 1}:
            issues.append(f"{label}: samples must cover below, equal and above")

    extra = set(check_by_key) - set(required)
    for key in sorted(extra):
        issues.append(f"boundary check has no numeric rule condition: {'/'.join(key)}")
    return tuple(issues)


def _parse_promotion_spec(
    project_root: Path,
    item: dict[str, Any],
) -> RulepackPromotionSpec:
    approvals = tuple(
        PromotionApproval(
            role=_required_string(approval, "role"),
            status=_required_string(approval, "status"),
            reviewer=approval.get("reviewer"),
            reviewed_at=(
                datetime.fromisoformat(approval["reviewed_at"])
                if approval.get("reviewed_at")
                else None
            ),
            commit_sha=approval.get("commit_sha"),
            rulepack_hash=approval.get("rulepack_hash"),
            validation_suite_hash=approval.get("validation_suite_hash"),
            reviewer_organization=approval.get("reviewer_organization"),
            authority_basis=approval.get("authority_basis"),
            evidence_content_hash=approval.get("evidence_content_hash"),
        )
        for approval in item.get("approvals", [])
    )
    required_roles = tuple(item.get("required_roles", []))
    if not required_roles or len(set(required_roles)) != len(required_roles):
        raise ValueError("required_roles must be unique and non-empty")
    return RulepackPromotionSpec(
        pack_id=_required_string(item, "pack_id"),
        rulepack_path=_project_path(
            project_root, _required_string(item, "rulepack_path")
        ),
        validation_suite_path=_project_path(
            project_root, _required_string(item, "validation_suite_path")
        ),
        required_roles=required_roles,
        approvals=approvals,
    )


def _required_string(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _project_path(project_root: Path, value: str) -> Path:
    root = project_root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path escapes project root: {value}")
    return path
