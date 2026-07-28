import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from tradeflow.domain.enums import DecisionStatus, RuleType
from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.models import (
    Condition,
    KnowledgeRule,
    ReviewPolicy,
    SourceRecord,
)
from tradeflow.knowledge.facts import FactCatalog
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.knowledge.validation import (
    PromotionApproval,
    RuleValidationSuite,
    audit_rulepack_readiness,
    load_promotion_manifest,
    validate_rule_suite,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REGISTRY = PROJECT_ROOT / "knowledge" / "source_registry.json"
PROMOTION_MANIFEST = (
    PROJECT_ROOT / "knowledge" / "reviews" / "rulepack_promotion.json"
)
FACT_CATALOG = FactCatalog.from_json(
    PROJECT_ROOT / "knowledge" / "fact_catalog.json"
)


class ReviewPolicyTests(unittest.TestCase):
    def test_validated_rule_can_still_require_expert_confirmation(self) -> None:
        source = SourceRecord(
            "S1",
            "Official",
            "Authority",
            "https://example.test/source",
            True,
            datetime.fromisoformat("2026-07-01T00:00:00+09:00"),
            verified=True,
        )
        rule = KnowledgeRule(
            "R1",
            "Reviewed rule",
            "topic",
            RuleType.PROCEDURE,
            (Condition("fact", "eq", True),),
            ("S1",),
            production_ready=True,
            review_policy=ReviewPolicy.ALWAYS_EXPERT,
        )

        decision = KnowledgeRepository((source,), (rule,)).evaluate(
            topic="topic",
            facts={"fact": True},
            as_of=date(2026, 7, 27),
        )[0]

        self.assertTrue(decision.matched)
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            decision.status,
        )
        self.assertIn("rule policy", decision.reasons[-1])


class RulepackPromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.specs = load_promotion_manifest(
            PROJECT_ROOT,
            PROMOTION_MANIFEST,
        )

    def test_committed_golden_suites_cover_every_rule_three_ways(self) -> None:
        self.assertEqual(
            {"KSURE_MVP_CANDIDATES", "FX_COMPLIANCE_MVP"},
            {item.pack_id for item in self.specs},
        )
        for spec in self.specs:
            with self.subTest(pack_id=spec.pack_id):
                report = audit_rulepack_readiness(
                    project_root=PROJECT_ROOT,
                    source_registry_path=SOURCE_REGISTRY,
                    spec=spec,
                )
                self.assertTrue(report.validation.passed, report.validation.issues)
                self.assertFalse(report.integrity_issues)
                self.assertFalse(report.ready)
                self.assertIn(
                    "pending approval: platform_runtime",
                    report.blockers,
                )
                self.assertIn(
                    "pending approval: domain_expert",
                    report.blockers,
                )

    def test_changed_expected_outcome_fails_the_suite(self) -> None:
        spec = next(item for item in self.specs if item.pack_id == "KSURE_MVP_CANDIDATES")
        suite = RuleValidationSuite.from_json(spec.validation_suite_path)
        first = suite.cases[0]
        changed_expectation = replace(
            first.expectations[0],
            status=DecisionStatus.NOT_ELIGIBLE,
        )
        changed_suite = replace(
            suite,
            cases=(
                replace(
                    first,
                    expectations=(changed_expectation, *first.expectations[1:]),
                ),
                *suite.cases[1:],
            ),
        )
        repository = KnowledgeRepository.from_json(
            SOURCE_REGISTRY,
            spec.rulepack_path,
        )

        report = validate_rule_suite(changed_suite, repository)

        self.assertFalse(report.passed)
        self.assertTrue(any("status" in issue for issue in report.issues))

    def test_numeric_threshold_change_cannot_hide_behind_other_cases(self) -> None:
        spec = next(item for item in self.specs if item.pack_id == "KSURE_MVP_CANDIDATES")
        suite = RuleValidationSuite.from_json(spec.validation_suite_path)
        repository = KnowledgeRepository.from_json(
            SOURCE_REGISTRY,
            spec.rulepack_path,
        )
        target_id = "KSURE_SHORT_TERM_EXPORT_POSTSHIP_INDIVIDUAL_CANDIDATE"
        target = repository.rules[target_id]
        changed_conditions = tuple(
            replace(condition, value=731)
            if condition.field == "trade.payment_term_days"
            else condition
            for condition in target.conditions
        )
        changed_rules = tuple(
            replace(rule, conditions=changed_conditions)
            if rule.rule_id == target_id
            else rule
            for rule in repository.rules.values()
        )
        changed_repository = KnowledgeRepository(
            repository.sources.values(),
            changed_rules,
            repository.document_sets.values(),
        )

        report = validate_rule_suite(suite, changed_repository)

        self.assertTrue(
            any("rule threshold 731 != golden 730" in issue for issue in report.issues)
        )

    def test_every_numeric_condition_requires_three_sided_boundary_data(self) -> None:
        spec = next(item for item in self.specs if item.pack_id == "KSURE_MVP_CANDIDATES")
        suite = RuleValidationSuite.from_json(spec.validation_suite_path)
        repository = KnowledgeRepository.from_json(
            SOURCE_REGISTRY,
            spec.rulepack_path,
        )

        report = validate_rule_suite(
            replace(suite, boundary_checks=()),
            repository,
        )

        self.assertIn(
            "missing numeric boundary check: "
            "KSURE_SHORT_TERM_EXPORT_POSTSHIP_INDIVIDUAL_CANDIDATE/"
            "trade.payment_term_days/lte",
            report.issues,
        )

    def test_golden_facts_must_obey_the_runtime_fact_catalog(self) -> None:
        spec = next(item for item in self.specs if item.pack_id == "KSURE_MVP_CANDIDATES")
        suite = RuleValidationSuite.from_json(spec.validation_suite_path)
        original = suite.cases[1]
        invalid = replace(
            original,
            facts={**original.facts, "trade.direction": "domestic"},
        )
        repository = KnowledgeRepository.from_json(
            SOURCE_REGISTRY,
            spec.rulepack_path,
        )

        report = validate_rule_suite(
            replace(suite, cases=(suite.cases[0], invalid, *suite.cases[2:])),
            repository,
            FACT_CATALOG,
        )

        self.assertTrue(
            any("invalid golden fact" in issue for issue in report.issues)
        )

    def test_production_flags_are_rejected_while_approvals_are_pending(self) -> None:
        base = next(item for item in self.specs if item.pack_id == "FX_COMPLIANCE_MVP")
        payload = json.loads(base.rulepack_path.read_text(encoding="utf-8"))
        payload["status"] = "active"
        for rule in payload["rules"]:
            rule["production_ready"] = True

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fx.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            spec = replace(base, rulepack_path=path)
            report = audit_rulepack_readiness(
                project_root=PROJECT_ROOT,
                source_registry_path=SOURCE_REGISTRY,
                spec=spec,
            )

        self.assertTrue(
            any("production state is forbidden" in issue for issue in report.integrity_issues)
        )

    def test_rulepack_cannot_be_partially_promoted(self) -> None:
        base = next(item for item in self.specs if item.pack_id == "FX_COMPLIANCE_MVP")
        payload = json.loads(base.rulepack_path.read_text(encoding="utf-8"))
        payload["rules"][0]["production_ready"] = True

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fx.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            report = audit_rulepack_readiness(
                project_root=PROJECT_ROOT,
                source_registry_path=SOURCE_REGISTRY,
                spec=replace(base, rulepack_path=path),
            )

        self.assertIn(
            "FX_COMPLIANCE_MVP: partial production_ready state is forbidden",
            report.integrity_issues,
        )

    def test_string_production_flag_is_not_truthy_coerced(self) -> None:
        base = next(item for item in self.specs if item.pack_id == "FX_COMPLIANCE_MVP")
        payload = json.loads(base.rulepack_path.read_text(encoding="utf-8"))
        payload["rules"][0]["production_ready"] = "false"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fx.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "production_ready must be boolean"):
                KnowledgeRepository.from_json(SOURCE_REGISTRY, path)

    def test_approved_review_requires_auditable_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "needs reviewer"):
            PromotionApproval("platform_runtime", "approved")

    def test_approval_is_bound_to_exact_rulepack_and_suite_hashes(self) -> None:
        base = next(item for item in self.specs if item.pack_id == "FX_COMPLIANCE_MVP")
        raw_pack = json.loads(base.rulepack_path.read_text(encoding="utf-8"))
        raw_suite = json.loads(
            base.validation_suite_path.read_text(encoding="utf-8")
        )
        approvals = tuple(
            PromotionApproval(
                role,
                "approved",
                reviewer=f"reviewer-{role}",
                reviewed_at=datetime.fromisoformat(
                    "2026-07-27T20:00:00+09:00"
                ),
                commit_sha="37e8b45",
                rulepack_hash=content_hash(raw_pack),
                validation_suite_hash=content_hash(raw_suite),
                reviewer_organization=(
                    "Independent Authority" if role == "domain_expert" else None
                ),
                authority_basis=(
                    "official written interpretation"
                    if role == "domain_expert"
                    else None
                ),
                evidence_content_hash=(
                    "sha256:" + "1" * 64 if role == "domain_expert" else None
                ),
            )
            for role in base.required_roles
        )
        approved = replace(base, approvals=approvals)
        valid = audit_rulepack_readiness(
            project_root=PROJECT_ROOT,
            source_registry_path=SOURCE_REGISTRY,
            spec=approved,
        )
        self.assertFalse(valid.integrity_issues)
        self.assertNotIn("pending approval: platform_runtime", valid.blockers)

        stale = replace(
            approved,
            approvals=(
                replace(approvals[0], rulepack_hash="sha256:" + "0" * 64),
                *approvals[1:],
            ),
        )
        invalid = audit_rulepack_readiness(
            project_root=PROJECT_ROOT,
            source_registry_path=SOURCE_REGISTRY,
            spec=stale,
        )
        self.assertTrue(
            any("approval rulepack hash is stale" in issue for issue in invalid.integrity_issues)
        )

    def test_domain_expert_requires_independent_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "organization"):
            PromotionApproval(
                "domain_expert",
                "approved",
                reviewer="rule-author",
                reviewed_at=datetime.fromisoformat("2026-07-28T20:00:00+09:00"),
                commit_sha="37e8b45",
                rulepack_hash="sha256:" + "1" * 64,
                validation_suite_hash="sha256:" + "2" * 64,
            )


if __name__ == "__main__":
    unittest.main()
