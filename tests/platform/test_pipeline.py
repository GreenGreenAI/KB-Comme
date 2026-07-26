import unittest
from datetime import date, datetime
from decimal import Decimal

from tradeflow.domain.enums import (
    DecisionStatus,
    PaymentMethod,
    RuleType,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.models import Condition, KnowledgeRule, SourceRecord
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline


class PipelineTests(unittest.TestCase):
    def _program(self, is_sme: bool | None = True) -> TradeProgram:
        return TradeProgram(
            "P1",
            CompanyProfile("C1", "Test", is_sme=is_sme),
            (
                TradeCase(
                    "E1", TradeDirection.EXPORT, "USD", Decimal("1000"),
                    date(2026, 8, 1), PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 26),
        )

    def _knowledge(self, *, verified: bool, production_ready: bool) -> KnowledgeRepository:
        source = SourceRecord(
            "S1", "Source", "Authority", "https://example.test/source", True,
            datetime(2026, 7, 1), date(2026, 1, 1), date(2026, 12, 31),
            "sha256:test", verified,
        )
        rule = KnowledgeRule(
            "R1", "SME export", "trade_support", RuleType.ELIGIBILITY,
            (
                Condition("company.is_sme", "eq", True),
                Condition("program.has_export", "eq", True),
            ),
            ("S1",),
            date(2026, 1, 1),
            date(2026, 12, 31),
            production_ready=production_ready,
        )
        return KnowledgeRepository((source,), (rule,))

    def test_verified_production_rule_can_return_candidate(self) -> None:
        result = TradeFlowPipeline(
            self._knowledge(verified=True, production_ready=True)
        ).analyze(self._program())

        self.assertEqual(DecisionStatus.ELIGIBLE_CANDIDATE, result.decisions[0].status)
        self.assertFalse(result.review_required)
        self.assertTrue(result.evidence_coverage["satisfied"])

    def test_unverified_source_forces_review(self) -> None:
        result = TradeFlowPipeline(
            self._knowledge(verified=False, production_ready=False)
        ).analyze(self._program())

        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            result.decisions[0].status,
        )
        self.assertTrue(result.review_required)

    def test_missing_company_fact_is_not_guessed(self) -> None:
        result = TradeFlowPipeline(
            self._knowledge(verified=True, production_ready=True)
        ).analyze(self._program(is_sme=None))

        self.assertEqual(
            DecisionStatus.INSUFFICIENT_INFORMATION,
            result.decisions[0].status,
        )
        self.assertEqual(("company.is_sme",), result.decisions[0].missing_fields)
        self.assertTrue(result.review_required)


if __name__ == "__main__":
    unittest.main()
