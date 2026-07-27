import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from tradeflow.domain.enums import (
    DecisionStatus,
    PaymentMethod,
    RuleType,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.domain.snapshot import SnapshotRef
from tradeflow.knowledge.models import (
    Condition,
    ConditionFailureEffect,
    KnowledgeRule,
    SourceRecord,
)
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

    def test_conditional_candidate_requires_review(self) -> None:
        source = SourceRecord(
            "S1", "Source", "Authority", "https://example.test/source", True,
            datetime(2026, 7, 1), date(2026, 1, 1), date(2026, 12, 31),
            "sha256:test", True,
        )
        rule = KnowledgeRule(
            "R2", "Document conditional", "trade_support", RuleType.ELIGIBILITY,
            (
                Condition(
                    "company.has_required_document",
                    "eq",
                    True,
                    "필수 서류 제출",
                    ConditionFailureEffect.CONDITIONAL,
                ),
            ),
            ("S1",),
            date(2026, 1, 1),
            date(2026, 12, 31),
            production_ready=True,
        )

        result = TradeFlowPipeline(
            KnowledgeRepository((source,), (rule,))
        ).analyze(
            self._program().__class__(
                self._program().program_id,
                CompanyProfile(
                    "C1",
                    "Test",
                    is_sme=True,
                    attributes={"company.has_required_document": False},
                ),
                self._program().cases,
                as_of=self._program().as_of,
            )
        )

        self.assertEqual(
            DecisionStatus.CONDITIONALLY_ELIGIBLE,
            result.decisions[0].status,
        )
        self.assertTrue(result.review_required)

    def test_input_snapshot_lineage_reaches_evidence_and_packet(self) -> None:
        ref = SnapshotRef(
            source_id="ERP_TRADE_FEED",
            version="erp-v1",
            observed_at=datetime(2026, 7, 26, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 26, 1, tzinfo=UTC),
            content_hash="sha256:input",
        )
        base = self._program()
        program = TradeProgram(
            base.program_id,
            base.company,
            base.cases,
            as_of=base.as_of,
            input_snapshots=(ref,),
        )

        pipeline = TradeFlowPipeline(
            self._knowledge(verified=True, production_ready=True)
        )
        result = pipeline.analyze(program)
        packet = pipeline.analyze_packet(program)

        trade_evidence = result.evidence[0]
        self.assertEqual(("ERP_TRADE_FEED",), trade_evidence.source_ids)
        self.assertEqual(
            "erp-v1", trade_evidence.payload["snapshots"][0]["version"]
        )
        packet_inputs = {item.name: item.value for item in packet.inputs}
        self.assertIn("program.input_snapshots", packet_inputs)
        self.assertEqual(
            ("ERP_TRADE_FEED",),
            packet.evidence[0].source_ids,
        )


if __name__ == "__main__":
    unittest.main()
