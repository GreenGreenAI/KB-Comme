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
from tradeflow.knowledge.eligibility_evidence import (
    CompanyQualificationEvidence,
    EligibilityEvidenceAssembler,
    EligibilityEvidenceRecord,
    EvidenceMetadata,
    EvidenceSubjectKind,
    KsureCreditEvidence,
    KsureCreditSubject,
)
from tradeflow.knowledge.ksure import KsureCaseProfile, bind_country_policy
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline
from tradeflow.runtime.analysis_service import decision_packet_document

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

        self.assertEqual("1.6", packet.schema_version)
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
        self.assertTrue(all(action.document_set_ids for action in packet.actions))
        self.assertTrue(all(action.document_requirements for action in packet.actions))
        self.assertTrue(all(action.steps for action in packet.actions))

        short_term = next(
            action
            for action in packet.actions
            if "ksure_short_term_export_postshipment_individual"
            in action.product_ids
        )
        self.assertEqual((), short_term.required_documents)
        trade_form = short_term.document_requirements[0]
        self.assertEqual("one_of", trade_form.kind.value)
        self.assertEqual("trade.transaction_type", trade_form.selector_field)
        self.assertEqual(3, len(trade_form.documents))
        self.assertIn(
            "KSURE_SHORT_TERM_POSTSHIP_APPLICATION_DOCUMENTS",
            short_term.source_ids,
        )
        self.assertIn(
            "KSURE_SHORT_TERM_POSTSHIP_APPLICATION_FORMS",
            short_term.source_claim_ids,
        )
        document = decision_packet_document(packet)
        serialized = next(
            action
            for action in document["actions"]
            if "ksure_short_term_export_postshipment_individual"
            in action["product_ids"]
        )
        self.assertEqual(
            "one_of",
            serialized["document_requirements"][0]["kind"],
        )
        self.assertEqual(
            "trade.transaction_type",
            serialized["document_requirements"][0]["selector_field"],
        )

    def test_provider_evidence_enters_the_real_case_pipeline(self) -> None:
        def meta(evidence_id: str, source_id: str, digit: str) -> EvidenceMetadata:
            return EvidenceMetadata(
                evidence_id=evidence_id,
                source_id=source_id,
                observed_at=datetime(2026, 7, 27, 8, tzinfo=UTC),
                retrieved_at=datetime(2026, 7, 27, 9, tzinfo=UTC),
                valid_until=datetime(2026, 8, 27, tzinfo=UTC),
                content_hash="sha256:" + digit * 64,
            )

        records = (
            CompanyQualificationEvidence(
                metadata=meta("company:C1", "COMPANY_QUALIFICATION", "1"),
                company_id="C1",
                provider_key="company_qualification",
                company_size="small",
                credit_issue_free=True,
            ).to_record(),
            KsureCreditEvidence(
                metadata=meta("ksure-exporter:C1", "KSURE_CREDIT", "2"),
                subject=KsureCreditSubject.EXPORTER,
                subject_id="C1",
                company_id="C1",
                grade="A",
                provider_key="ksure_credit",
            ).to_record(),
            KsureCreditEvidence(
                metadata=meta("ksure-importer:EXP-1", "KSURE_CREDIT", "3"),
                subject=KsureCreditSubject.IMPORTER,
                subject_id="EXP-1",
                company_id="C1",
                grade="B",
                provider_key="ksure_credit",
            ).to_record(),
            EligibilityEvidenceRecord(
                metadata=meta("country-policy:EXP-1", "KSURE_COUNTRY_POLICY", "4"),
                subject_kind=EvidenceSubjectKind.CASE,
                subject_id="EXP-1",
                company_id="C1",
                facts={"counterparty.country_restricted": False},
                provider_key="ksure_country_policy",
            ),
        )
        eligibility = EligibilityEvidenceAssembler(
            FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json"),
            trusted_source_ids={
                "COMPANY_QUALIFICATION",
                "KSURE_CREDIT",
                "KSURE_COUNTRY_POLICY",
            },
        ).assemble(
            program=self.program,
            records=records,
            evaluated_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
            required_fields_by_case={
                "EXP-1": tuple(self.support_facts),
            },
        )
        remaining_profile = KsureCaseProfile(
            payment_term_days=180,
            financing_purpose="trade_finance",
            has_bank_consultation=True,
            evidence_ids_by_field={
                **{
                    field: ("trade-terms:KSURE-1",)
                    for field in self.trade_facts
                },
                "financing.has_bank_consultation": ("procedure:KSURE-1",),
            },
        )

        packet = self.pipeline.analyze_case_packet_with_eligibility(
            self.program,
            eligibility=eligibility,
            assertions_by_case={"EXP-1": remaining_profile.assertions()},
            evidence=self.evidence[1:],
            source_freshness=self.freshness,
        )

        self.assertEqual(3, len(packet.decisions))
        self.assertTrue(all(item.matched for item in packet.decisions))
        input_by_name = {item.name: item.value for item in packet.inputs}
        eligibility_input = dict(input_by_name["eligibility_evidence"])
        self.assertEqual((), eligibility_input["stale_evidence_ids"])
        missing_by_case = dict(eligibility_input["missing_fields_by_case"])
        self.assertEqual((), missing_by_case["EXP-1"])
        evidence_ids = {item.evidence_id for item in packet.evidence}
        self.assertIn("company:C1", evidence_ids)
        self.assertIn("ksure-importer:EXP-1", evidence_ids)

    def test_stale_required_provider_evidence_is_audited_and_forces_review(self) -> None:
        stale = CompanyQualificationEvidence(
            metadata=EvidenceMetadata(
                evidence_id="company:C1:stale",
                source_id="COMPANY_QUALIFICATION",
                observed_at=datetime(2026, 7, 25, tzinfo=UTC),
                retrieved_at=datetime(2026, 7, 25, 1, tzinfo=UTC),
                valid_until=datetime(2026, 7, 26, tzinfo=UTC),
                content_hash="sha256:" + "5" * 64,
            ),
            company_id="C1",
            provider_key="company_qualification",
            company_size="small",
        ).to_record()
        eligibility = EligibilityEvidenceAssembler(
            FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json"),
            trusted_source_ids={"COMPANY_QUALIFICATION"},
        ).assemble(
            program=self.program,
            records=(stale,),
            evaluated_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
            required_fields_by_case={"EXP-1": ("company.size",)},
        )

        result = self.pipeline.analyze_cases_with_eligibility(
            self.program,
            eligibility=eligibility,
            source_freshness=self.freshness,
        )

        self.assertTrue(result.review_required)
        self.assertIn(
            "EXP-1: missing eligibility evidence: company.size",
            result.review_reasons,
        )
        self.assertIn(
            "stale eligibility evidence: company:C1:stale",
            result.review_reasons,
        )
        stale_evidence = next(
            item for item in result.evidence if item.evidence_id == "company:C1:stale"
        )
        self.assertEqual("stale", stale_evidence.payload["usability"])
        self.assertNotIn("facts", stale_evidence.payload)

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
