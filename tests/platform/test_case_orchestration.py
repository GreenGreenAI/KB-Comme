import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from tradeflow.contracts.decision_packet import (
    DecisionStatusClaim,
    SynthesisResult,
    validate_synthesis,
)
from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import (
    DecisionStatus,
    EvidenceRole,
    Freshness,
    PaymentMethod,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.facts import FactAssembler, FactAssertion, FactCatalog
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline

ROOT = Path(__file__).resolve().parents[2]


class CaseOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge = KnowledgeRepository.from_json_files(
            ROOT / "knowledge" / "source_registry.json",
            (
                ROOT / "knowledge" / "rulepacks" / "ksure_mvp_candidates.json",
                ROOT / "knowledge" / "rulepacks" / "fx_compliance_mvp.json",
            ),
        )
        cls.pipeline = TradeFlowPipeline(
            cls.knowledge,
            fact_assembler=FactAssembler(
                FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json")
            ),
        )

    def setUp(self) -> None:
        case = TradeCase(
            "EXP-1",
            TradeDirection.EXPORT,
            "USD",
            Decimal("100000"),
            date(2026, 9, 30),
            PaymentMethod.TT,
        )
        self.program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Exporter", country_code="KR"),
            (case,),
            as_of=date(2026, 7, 27),
        )
        moment = datetime(2026, 7, 27, tzinfo=UTC)
        self.evidence = (
            EvidenceDescriptor(
                "compliance:MA1",
                EvidenceRole.COMPLIANCE,
                ("EXP-1", "mutual-account-contract"),
                generated_at=moment,
                payload={
                    "facts": {
                        "payment.uses_mutual_account": True,
                        "payment.mutual_account.party_count": 2,
                    }
                },
            ),
            EvidenceDescriptor(
                "procedure:MA1",
                EvidenceRole.PROCEDURE,
                ("EXP-1", "bank-filing-status"),
                generated_at=moment,
                payload={
                    "facts": {
                        "payment.mutual_account.opening_filing_completed": False
                    }
                },
            ),
        )
        self.assertions = {
            "EXP-1": (
                FactAssertion(
                    "payment.uses_mutual_account",
                    True,
                    ("compliance:MA1",),
                ),
                FactAssertion(
                    "payment.mutual_account.party_count",
                    2,
                    ("compliance:MA1",),
                ),
                FactAssertion(
                    "payment.mutual_account.opening_filing_completed",
                    False,
                    ("procedure:MA1",),
                ),
            )
        }
        self.freshness = {
            source_id: Freshness.FRESH
            for source_id in self.knowledge.sources
        }

    def test_mutual_account_case_reaches_real_fx_rule_and_packet(self) -> None:
        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case=self.assertions,
            evidence=self.evidence,
            source_freshness=self.freshness,
        )

        opening = next(
            item
            for item in packet.decisions
            if item.rule_id == "FX_MUTUAL_ACCOUNT_OPENING_BANK_FILING_CANDIDATE"
        )
        self.assertEqual("EXP-1", opening.subject_id)
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            opening.status,
        )
        self.assertEqual(
            "file_mutual_account_opening",
            dict(opening.candidate_outcome)["action"],
        )
        self.assertTrue(packet.review_required)
        self.assertTrue(
            any(
                item.evidence_id
                == "decision:EXP-1:FX_MUTUAL_ACCOUNT_OPENING_BANK_FILING_CANDIDATE"
                for item in packet.evidence
            )
        )
        inputs = {item.name: item.value for item in packet.inputs}
        cases = dict(inputs["cases"])
        facts = dict(cases["EXP-1"])
        self.assertTrue(facts["payment.uses_mutual_account"])

    def test_unknown_case_assertions_are_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown cases"):
            self.pipeline.analyze_cases(
                self.program,
                assertions_by_case={"MISSING": ()},
                evidence=self.evidence,
                source_freshness=self.freshness,
            )

    def test_llm_cannot_drop_case_identity_from_rule_decisions(self) -> None:
        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case=self.assertions,
            evidence=self.evidence,
            source_freshness=self.freshness,
        )
        claims = tuple(
            DecisionStatusClaim(
                item.rule_id,
                item.status,
                item.subject_id,
            )
            for item in packet.decisions
        )
        first = claims[0]
        altered = (
            DecisionStatusClaim(first.rule_id, first.status, None),
            *claims[1:],
        )
        synthesis = SynthesisResult(
            packet_id=packet.packet_id,
            narrative="case identity was dropped",
            decision_statuses=altered,
            numeric_claims=(),
            evidence_ids=(),
            review_required=packet.review_required,
            review_reasons=packet.review_reasons,
        )

        self.assertIn(
            "decision statuses must exactly match the packet",
            validate_synthesis(packet, synthesis),
        )

    def test_packet_identity_changes_when_asserted_fact_changes(self) -> None:
        first = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case=self.assertions,
            evidence=self.evidence,
            source_freshness=self.freshness,
        )
        changed_assertions = {
            "EXP-1": (
                *self.assertions["EXP-1"][:2],
                FactAssertion(
                    "payment.mutual_account.opening_filing_completed",
                    True,
                    ("procedure:MA1-complete",),
                ),
            )
        }
        changed_evidence = (
            self.evidence[0],
            EvidenceDescriptor(
                "procedure:MA1-complete",
                EvidenceRole.PROCEDURE,
                ("EXP-1", "bank-filing-status"),
                generated_at=datetime(2026, 7, 27, tzinfo=UTC),
                payload={
                    "facts": {
                        "payment.mutual_account.opening_filing_completed": True
                    }
                },
            ),
        )

        second = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case=changed_assertions,
            evidence=changed_evidence,
            source_freshness=self.freshness,
        )

        self.assertNotEqual(first.packet_id, second.packet_id)

    def test_case_analysis_requires_configured_fact_assembler(self) -> None:
        with self.assertRaisesRegex(ValueError, "FactAssembler"):
            TradeFlowPipeline(self.knowledge).analyze_cases(
                self.program,
                assertions_by_case=self.assertions,
                evidence=self.evidence,
                source_freshness=self.freshness,
            )


if __name__ == "__main__":
    unittest.main()
