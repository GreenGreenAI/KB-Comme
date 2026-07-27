import unittest
from datetime import date, datetime
from pathlib import Path

from tradeflow.domain.enums import (
    DecisionCategory,
    DecisionStatus,
    Freshness,
    RuleType,
    SourceStatus,
)
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.knowledge.models import (
    Condition,
    ConditionFailureEffect,
    KnowledgeRule,
    SourceRecord,
)
from tradeflow.knowledge.repository import KnowledgeRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _source(
    *,
    verified: bool = True,
    effective_from: date | None = date(2026, 1, 1),
    effective_to: date | None = date(2026, 12, 31),
    freshness_required: bool = False,
) -> SourceRecord:
    return SourceRecord(
        source_id="S1",
        title="Official source",
        organization="Authority",
        url="https://example.test/source",
        official=True,
        retrieved_at=datetime.fromisoformat("2026-07-01T00:00:00+09:00"),
        effective_from=effective_from,
        effective_to=effective_to,
        verified=verified,
        freshness_required=freshness_required,
    )


def _rule(*conditions: Condition) -> KnowledgeRule:
    return KnowledgeRule(
        rule_id="R1",
        title="Conditional support",
        topic="trade_support",
        rule_type=RuleType.ELIGIBILITY,
        conditions=conditions,
        source_ids=("S1",),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        production_ready=True,
    )


class SourceStatusCompositionTests(unittest.TestCase):
    def test_authority_and_effective_period_precede_freshness(self) -> None:
        target = date(2026, 7, 27)

        self.assertEqual(
            SourceStatus.UNVERIFIED,
            _source(verified=False, freshness_required=True).status_on(
                target,
                freshness=Freshness.STALE,
            ),
        )
        self.assertEqual(
            SourceStatus.FUTURE,
            _source(
                effective_from=date(2026, 8, 1),
                freshness_required=True,
            ).status_on(target, freshness=Freshness.STALE),
        )
        self.assertEqual(
            SourceStatus.EXPIRED,
            _source(
                effective_to=date(2026, 7, 1),
                freshness_required=True,
            ).status_on(target, freshness=Freshness.FRESH),
        )

    def test_active_source_requires_declared_freshness_when_configured(self) -> None:
        source = _source(freshness_required=True)
        target = date(2026, 7, 27)

        self.assertEqual(SourceStatus.FRESHNESS_UNKNOWN, source.status_on(target))
        self.assertEqual(
            SourceStatus.STALE,
            source.status_on(target, freshness=Freshness.STALE),
        )
        self.assertEqual(
            SourceStatus.ACTIVE,
            source.status_on(target, freshness=Freshness.FRESH),
        )


class ConditionalDecisionTests(unittest.TestCase):
    def test_expired_source_is_classified_as_unusable(self) -> None:
        repository = KnowledgeRepository(
            (_source(effective_to=date(2026, 7, 1)),),
            (_rule(Condition("company.is_sme", "eq", True)),),
        )

        decision = repository.evaluate(
            topic="trade_support",
            facts={"company.is_sme": True},
            as_of=date(2026, 7, 27),
        )[0]

        self.assertEqual(DecisionStatus.SOURCE_EXPIRED, decision.status)
        self.assertEqual(
            (
                DecisionCategory.CANDIDATE,
                DecisionCategory.SOURCE_UNUSABLE,
            ),
            decision.categories,
        )

    def test_known_remediable_failure_returns_structured_requirement(self) -> None:
        condition = Condition(
            "company.has_required_document",
            "eq",
            True,
            "필수 서류 제출",
            ConditionFailureEffect.CONDITIONAL,
        )
        repository = KnowledgeRepository((_source(),), (_rule(condition),))

        decision = repository.evaluate(
            topic="trade_support",
            facts={"company.has_required_document": False},
            as_of=date(2026, 7, 27),
        )[0]

        self.assertEqual(DecisionStatus.CONDITIONALLY_ELIGIBLE, decision.status)
        self.assertEqual(1, len(decision.requirements))
        requirement = decision.requirements[0]
        self.assertEqual("company.has_required_document", requirement.field)
        self.assertEqual(True, requirement.expected_value)
        self.assertEqual(False, requirement.current_value)
        self.assertEqual(
            (DecisionCategory.CANDIDATE,),
            decision.categories,
        )

    def test_missing_fact_is_information_gap_not_conditional_eligibility(self) -> None:
        condition = Condition(
            "company.has_required_document",
            "eq",
            True,
            "필수 서류 제출",
            ConditionFailureEffect.CONDITIONAL,
        )
        repository = KnowledgeRepository((_source(),), (_rule(condition),))

        decision = repository.evaluate(
            topic="trade_support",
            facts={},
            as_of=date(2026, 7, 27),
        )[0]

        self.assertEqual(DecisionStatus.INSUFFICIENT_INFORMATION, decision.status)
        self.assertEqual(("company.has_required_document",), decision.missing_fields)
        self.assertEqual((), decision.requirements)
        self.assertEqual(
            (DecisionCategory.MISSING_INFORMATION,),
            decision.categories,
        )

    def test_hard_rejection_precedes_remediable_condition(self) -> None:
        repository = KnowledgeRepository(
            (_source(),),
            (
                _rule(
                    Condition("company.is_sme", "eq", True, "중소기업 여부"),
                    Condition(
                        "company.has_required_document",
                        "eq",
                        True,
                        "필수 서류 제출",
                        ConditionFailureEffect.CONDITIONAL,
                    ),
                ),
            ),
        )

        decision = repository.evaluate(
            topic="trade_support",
            facts={
                "company.is_sme": False,
                "company.has_required_document": False,
            },
            as_of=date(2026, 7, 27),
        )[0]

        self.assertEqual(DecisionStatus.NOT_ELIGIBLE, decision.status)
        self.assertEqual((), decision.requirements)
        self.assertEqual(
            (DecisionCategory.EXCLUDED,),
            decision.categories,
        )


class EcosRegistryTests(unittest.TestCase):
    def test_registered_source_matches_committed_snapshot_identity(self) -> None:
        repository = KnowledgeRepository.from_json(
            PROJECT_ROOT / "knowledge" / "source_registry.json",
            PROJECT_ROOT / "knowledge" / "rulepacks" / "demo_trade_support.json",
        )
        source = repository.sources["ECOS_USD_KRW"]
        ref, _ = read_snapshot(
            PROJECT_ROOT
            / "data"
            / "snapshots"
            / "ECOS_USD_KRW"
            / "2026-07-24.json"
        )

        self.assertTrue(source.official)
        self.assertTrue(source.verified)
        self.assertTrue(source.freshness_required)
        self.assertEqual(source.source_id, ref.source_id)
        self.assertEqual("한국은행 경제통계시스템(ECOS)", source.attribution)


if __name__ == "__main__":
    unittest.main()
