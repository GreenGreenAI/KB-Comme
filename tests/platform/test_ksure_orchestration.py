import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import (
    DecisionCategory,
    DecisionStatus,
    EvidenceRole,
    Freshness,
    PaymentMethod,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.domain.datasets import SnapshotDataset, parse_ksure_country_policy_payload
from tradeflow.domain.snapshot import SnapshotRef
from tradeflow.knowledge.facts import (
    FactAssembler,
    FactCatalog,
    FactContractError,
)
from tradeflow.knowledge.ksure import KsureCaseProfile, bind_country_policy
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline

ROOT = Path(__file__).resolve().parents[2]


class KsureOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.knowledge = KnowledgeRepository.from_json(
            ROOT / "knowledge" / "source_registry.json",
            ROOT / "knowledge" / "rulepacks" / "ksure_mvp_candidates.json",
        )
        cls.pipeline = TradeFlowPipeline(
            cls.knowledge,
            fact_assembler=FactAssembler(
                FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json")
            ),
        )

    def setUp(self) -> None:
        self.program = TradeProgram(
            "KSURE-P1",
            CompanyProfile("C1", "Exporter", country_code="KR"),
            (
                TradeCase(
                    "EXP-1",
                    TradeDirection.EXPORT,
                    "USD",
                    Decimal("100000"),
                    date(2026, 12, 1),
                    PaymentMethod.TT,
                    counterparty_country="US",
                ),
            ),
            as_of=date(2026, 7, 27),
        )
        moment = datetime(2026, 7, 27, tzinfo=UTC)
        self.support_facts = {
            "company.size": "small",
            "company.credit_issue_free": True,
            "company.ksure_exporter_grade": "A",
            "counterparty.ksure_importer_grade": "B",
            "counterparty.country_restricted": False,
        }
        self.trade_facts = {
            "trade.payment_term_days": 180,
            "financing.purpose": "trade_finance",
        }
        self.procedure_facts = {
            "financing.has_bank_consultation": True,
        }
        self.evidence = (
            EvidenceDescriptor(
                "eligibility:KSURE-1",
                EvidenceRole.SUPPORT_ELIGIBILITY,
                ("EXP-1", "ksure-company-and-counterparty"),
                generated_at=moment,
                payload={"facts": self.support_facts},
            ),
            EvidenceDescriptor(
                "trade-terms:KSURE-1",
                EvidenceRole.USER_TRADE,
                ("EXP-1", "export-contract"),
                generated_at=moment,
                payload={"facts": self.trade_facts},
            ),
            EvidenceDescriptor(
                "procedure:KSURE-1",
                EvidenceRole.PROCEDURE,
                ("EXP-1", "bank-consultation"),
                generated_at=moment,
                payload={"facts": self.procedure_facts},
            ),
        )
        self.profile = self._profile()
        self.freshness = {
            source_id: Freshness.FRESH
            for source_id in self.knowledge.sources
        }

    def _profile(self, **changes) -> KsureCaseProfile:
        values = {
            "company_size": "small",
            "credit_issue_free": True,
            "exporter_grade": "A",
            "importer_grade": "B",
            "country_restricted": False,
            "payment_term_days": 180,
            "financing_purpose": "trade_finance",
            "has_bank_consultation": True,
            "evidence_ids_by_field": {
                **{
                    field: ("eligibility:KSURE-1",)
                    for field in self.support_facts
                },
                **{
                    field: ("trade-terms:KSURE-1",)
                    for field in self.trade_facts
                },
                "financing.has_bank_consultation": ("procedure:KSURE-1",),
            },
        }
        values.update(changes)
        return KsureCaseProfile(**values)

    def _packet(self, profile: KsureCaseProfile | None = None):
        return self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case={
                "EXP-1": (profile or self.profile).assertions()
            },
            evidence=self.evidence,
            source_freshness=self.freshness,
        )

    def test_complete_case_reaches_three_products_and_action_plans(self) -> None:
        packet = self._packet()

        self.assertEqual("1.4", packet.schema_version)
        self.assertEqual(3, len(packet.decisions))
        for decision in packet.decisions:
            self.assertEqual(
                DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
                decision.status,
            )
            self.assertTrue(decision.matched)
            self.assertIn(DecisionCategory.CANDIDATE, decision.categories)
            self.assertIn(DecisionCategory.EXPERT_REVIEW, decision.categories)

        products = {
            product_id
            for action in packet.actions
            for product_id in action.product_ids
        }
        self.assertEqual(
            {
                "ksure_fx_insurance_general_export",
                "ksure_short_term_export_postshipment_individual",
                "ksure_export_credit_guarantee_preshipment",
            },
            products,
        )
        self.assertTrue(all(action.required_documents for action in packet.actions))
        self.assertTrue(all(action.steps for action in packet.actions))

    def test_country_policy_snapshot_supplies_restriction_fact_end_to_end(self) -> None:
        profile = self._profile(
            country_restricted=None,
            evidence_ids_by_field={
                field: evidence_ids
                for field, evidence_ids in self.profile.evidence_ids_by_field.items()
                if field != "counterparty.country_restricted"
            },
        )
        moment = datetime(2026, 7, 27, tzinfo=UTC)
        dataset = SnapshotDataset(
            SnapshotRef(
                "KSURE_COUNTRY_POLICY_API",
                "20260727T000000Z",
                moment,
                moment,
                "sha256:country-policy",
            ),
            parse_ksure_country_policy_payload(
                {
                    "schema_version": "1.0",
                    "directory": {
                        "getNationLst": [
                            {"stdInfrmCtryCd": "US", "trgtpsnNm": "미국"},
                            {"stdInfrmCtryCd": "SY", "trgtpsnNm": "시리아"},
                        ]
                    },
                    "policy_filters": {
                        "normal": {"selectFilterLst": [{"ggCode": "US"}]},
                        "conditional": {"selectFilterLst": []},
                        "restricted": {
                            "selectFilterLst": [{"ggCode": "SY"}]
                        },
                        "deep_watch": {"selectFilterLst": []},
                    },
                }
            ),
        )
        profile, policy_evidence = bind_country_policy(
            profile, dataset, self.program.cases[0]
        )

        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case={"EXP-1": profile.assertions()},
            evidence=(*self.evidence, policy_evidence),
            source_freshness=self.freshness,
        )

        short_term = next(
            item
            for item in packet.decisions
            if item.rule_id
            == "KSURE_SHORT_TERM_EXPORT_POSTSHIP_INDIVIDUAL_CANDIDATE"
        )
        self.assertTrue(short_term.matched)
        self.assertIn(
            policy_evidence.evidence_id,
            {item.evidence_id for item in packet.evidence},
        )

    def test_missing_bank_consultation_is_a_structured_requirement(self) -> None:
        procedure_facts = {"financing.has_bank_consultation": False}
        evidence = (
            *self.evidence[:2],
            EvidenceDescriptor(
                "procedure:KSURE-1",
                EvidenceRole.PROCEDURE,
                ("EXP-1", "bank-consultation"),
                generated_at=datetime(2026, 7, 27, tzinfo=UTC),
                payload={"facts": procedure_facts},
            ),
        )
        profile = self._profile(has_bank_consultation=False)
        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case={"EXP-1": profile.assertions()},
            evidence=evidence,
            source_freshness=self.freshness,
        )

        guarantee = next(
            item
            for item in packet.decisions
            if item.rule_id
            == "KSURE_EXPORT_CREDIT_GUARANTEE_PRESHIPMENT_CANDIDATE"
        )
        self.assertEqual(DecisionStatus.CONDITIONALLY_ELIGIBLE, guarantee.status)
        self.assertEqual(1, len(guarantee.requirements))
        action = next(
            item
            for item in packet.actions
            if "ksure_export_credit_guarantee_preshipment" in item.product_ids
        )
        self.assertEqual(1, len(action.requirements))

    def test_ineligible_grade_is_excluded_without_product_action(self) -> None:
        support_facts = dict(self.support_facts)
        support_facts["company.ksure_exporter_grade"] = "G"
        evidence = (
            EvidenceDescriptor(
                "eligibility:KSURE-1",
                EvidenceRole.SUPPORT_ELIGIBILITY,
                ("EXP-1", "ksure-company-and-counterparty"),
                generated_at=datetime(2026, 7, 27, tzinfo=UTC),
                payload={"facts": support_facts},
            ),
            *self.evidence[1:],
        )
        profile = self._profile(exporter_grade="G")
        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case={"EXP-1": profile.assertions()},
            evidence=evidence,
            source_freshness=self.freshness,
        )

        short_term = next(
            item
            for item in packet.decisions
            if item.rule_id
            == "KSURE_SHORT_TERM_EXPORT_POSTSHIP_INDIVIDUAL_CANDIDATE"
        )
        self.assertEqual(DecisionStatus.NOT_ELIGIBLE, short_term.status)
        self.assertFalse(short_term.matched)
        self.assertFalse(
            any(
                "ksure_short_term_export_postshipment_individual"
                in action.product_ids
                for action in packet.actions
            )
        )

    def test_profile_refuses_unproven_or_invalid_values(self) -> None:
        with self.assertRaisesRegex(FactContractError, "requires evidence_ids"):
            KsureCaseProfile(company_size="small").assertions()
        with self.assertRaisesRegex(ValueError, "non-negative"):
            KsureCaseProfile(payment_term_days=-1)


if __name__ == "__main__":
    unittest.main()
