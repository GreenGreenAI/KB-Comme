import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from tradeflow.contracts.decision_packet import (
    DecisionPacket,
    DecisionStatusClaim,
    HedgeModelClaim,
    NumericClaim,
    SynthesisResult,
    validate_synthesis,
)
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
from tradeflow.tools.hedge_models import HedgeModelDecision


class DecisionPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        source = SourceRecord(
            "S1",
            "Source",
            "Authority",
            "https://example.test/source",
            True,
            datetime(2026, 7, 1),
            date(2026, 1, 1),
            date(2026, 12, 31),
            "sha256:test",
            True,
        )
        rule = KnowledgeRule(
            "R1",
            "SME export",
            "trade_support",
            RuleType.ELIGIBILITY,
            (Condition("company.is_sme", "eq", True),),
            ("S1",),
            date(2026, 1, 1),
            date(2026, 12, 31),
            production_ready=True,
        )
        self.program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Test", is_sme=True),
            (
                TradeCase(
                    "E1",
                    TradeDirection.EXPORT,
                    "USD",
                    Decimal("1000"),
                    date(2026, 8, 1),
                    PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 26),
        )
        self.pipeline = TradeFlowPipeline(
            KnowledgeRepository((source,), (rule,))
        )
        self.packet = self.pipeline.analyze_packet(self.program)

    def _valid_result(self) -> SynthesisResult:
        return SynthesisResult(
            packet_id=self.packet.packet_id,
            narrative="The deterministic result is an eligible candidate.",
            decision_statuses=(
                DecisionStatusClaim("R1", DecisionStatus.ELIGIBLE_CANDIDATE),
            ),
            numeric_claims=(
                NumericClaim(
                    "exposures.USD.trade_net_exposure",
                    Decimal("1000"),
                ),
            ),
            evidence_ids=tuple(
                item.evidence_id for item in self.packet.evidence
            ),
            review_required=False,
            review_reasons=(),
        )

    def test_pipeline_builds_versioned_immutable_packet(self) -> None:
        self.assertEqual("1.6", self.packet.schema_version)
        currencies = next(
            item.value
            for item in self.packet.inputs
            if item.name == "program.currencies"
        )
        self.assertEqual(("USD",), currencies)
        calculation = next(
            item
            for item in self.packet.evidence
            if item.evidence_id == "calculation:P1"
        )
        self.assertEqual((("engine", "tradeflow.exposure.v1"),), calculation.payload)

    def test_packet_carries_one_explicit_versioned_hedge_champion(self) -> None:
        model_result = HedgeModelDecision(
            model_id="rolling_normal_profit_floor",
            model_version="1.0",
            objective="minimum_ratio_subject_to_adverse_profit_floor",
            recommended_ratio=Decimal("0.42"),
            sufficient=True,
            status="ok",
            adverse_rate=Decimal("1300"),
            forecast_lower=Decimal("1300"),
            forecast_upper=Decimal("1500"),
            breach_probability=0.05,
            expected_shortfall=Decimal("0"),
            estimated_cost=Decimal("42000"),
            scenario_count=199,
            parameters={"window": 60, "drift": 0},
        )

        packet = DecisionPacket.from_analysis(
            self.pipeline.analyze(self.program),
            as_of=self.program.as_of,
            inputs={"program_id": self.program.program_id},
            hedge_decisions=(model_result,),
            champion_model_id=model_result.model_id,
        )

        hedge = packet.hedge_decisions[0]
        self.assertTrue(hedge.is_champion)
        self.assertEqual(Decimal("0.42"), hedge.recommended_ratio)
        self.assertEqual("1.0", hedge.model_version)
        self.assertEqual(
            Decimal("0.42"),
            packet.numeric_claims()[
                "hedge_decisions.rolling_normal_profit_floor."
                "recommended_ratio"
            ],
        )
        synthesis = SynthesisResult(
            packet_id=packet.packet_id,
            narrative="The challenger is preferred.",
            decision_statuses=tuple(
                DecisionStatusClaim(
                    item.rule_id,
                    item.status,
                    subject_id=item.subject_id,
                )
                for item in packet.decisions
            ),
            numeric_claims=(),
            evidence_ids=tuple(
                item.evidence_id for item in packet.evidence
            ),
            review_required=packet.review_required,
            review_reasons=packet.review_reasons,
            hedge_models=(
                HedgeModelClaim(
                    model_id=model_result.model_id,
                    model_version=model_result.model_version,
                    is_champion=False,
                    status=model_result.status,
                ),
            ),
        )
        self.assertIn(
            "hedge model identity, version, champion and status must "
            "exactly match the packet",
            validate_synthesis(packet, synthesis),
        )

    def test_packet_rejects_missing_or_ambiguous_hedge_champion(self) -> None:
        model_result = HedgeModelDecision(
            model_id="challenger",
            model_version="1.0",
            objective="test",
            recommended_ratio=Decimal("0"),
            sufficient=True,
            status="ok",
            adverse_rate=Decimal("1300"),
            forecast_lower=Decimal("1300"),
            forecast_upper=Decimal("1500"),
            breach_probability=0,
            expected_shortfall=Decimal("0"),
            estimated_cost=Decimal("0"),
            scenario_count=10,
        )
        result = self.pipeline.analyze(self.program)

        with self.assertRaisesRegex(ValueError, "champion_model_id"):
            DecisionPacket.from_analysis(
                result,
                as_of=self.program.as_of,
                inputs={},
                hedge_decisions=(model_result,),
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            DecisionPacket.from_analysis(
                result,
                as_of=self.program.as_of,
                inputs={},
                hedge_decisions=(model_result, model_result),
                champion_model_id=model_result.model_id,
            )

    def test_same_analysis_has_the_same_content_addressed_packet_id(self) -> None:
        repeated = self.pipeline.analyze_packet(self.program)

        self.assertEqual(self.packet.packet_id, repeated.packet_id)

    def test_matching_synthesis_is_accepted(self) -> None:
        self.assertEqual((), validate_synthesis(self.packet, self._valid_result()))

    def test_llm_cannot_upgrade_or_change_decision_status(self) -> None:
        changed = replace(
            self._valid_result(),
            decision_statuses=(
                DecisionStatusClaim(
                    "R1",
                    DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
                ),
            ),
        )
        self.assertIn(
            "decision statuses must exactly match the packet",
            validate_synthesis(self.packet, changed),
        )

    def test_llm_cannot_recalculate_or_invent_numeric_claim(self) -> None:
        changed = replace(
            self._valid_result(),
            numeric_claims=(
                NumericClaim(
                    "exposures.USD.trade_net_exposure",
                    Decimal("999"),
                ),
                NumericClaim("recommendation.expected_profit", Decimal("1")),
            ),
        )
        errors = validate_synthesis(self.packet, changed)
        self.assertIn(
            "numeric claim changed packet value: "
            "exposures.USD.trade_net_exposure",
            errors,
        )
        self.assertIn(
            "numeric claim is not in the packet: recommendation.expected_profit",
            errors,
        )

    def test_llm_cannot_invent_evidence_or_hide_review(self) -> None:
        review_packet = replace(
            self.packet,
            review_required=True,
            review_reasons=("expert confirmation required",),
        )
        changed = replace(
            self._valid_result(),
            evidence_ids=("evidence:invented",),
            review_required=False,
            review_reasons=(),
        )
        errors = validate_synthesis(review_packet, changed)
        self.assertIn("unknown evidence_ids: evidence:invented", errors)
        self.assertIn("review_required must exactly match the packet", errors)
        self.assertIn("review_reasons must exactly match the packet", errors)


if __name__ == "__main__":
    unittest.main()
