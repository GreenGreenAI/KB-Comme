import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import EvidenceRole, PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.eligibility_evidence import (
    CompanyQualificationEvidence,
    EligibilityEvidenceAssembler,
    EligibilityEvidenceRecord,
    EligibilityProviderRegistry,
    EvidenceMetadata,
    EvidenceSubjectKind,
    KsureCreditEvidence,
    KsureCreditSubject,
)
from tradeflow.knowledge.facts import FactAssembler, FactCatalog, FactContractError


ROOT = Path(__file__).resolve().parents[2]
MOMENT = datetime(2026, 7, 27, 12, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def metadata(
    evidence_id: str,
    *,
    source_id: str = "TRUSTED_COMPANY_SOURCE",
    valid_until: datetime | None = None,
    content_hash: str = HASH_A,
) -> EvidenceMetadata:
    return EvidenceMetadata(
        evidence_id=evidence_id,
        source_id=source_id,
        observed_at=MOMENT - timedelta(hours=2),
        retrieved_at=MOMENT - timedelta(hours=1),
        valid_until=valid_until,
        content_hash=content_hash,
    )


class StaticProvider:
    def __init__(self, key: str, records: tuple[EligibilityEvidenceRecord, ...]):
        self.provider_key = key
        self.records = records

    def collect(self, *, program, evaluated_at):
        return self.records


class EligibilityEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json")

    def setUp(self) -> None:
        self.export_case = TradeCase(
            "EXP-1",
            TradeDirection.EXPORT,
            "USD",
            Decimal("100000"),
            date(2026, 10, 1),
            PaymentMethod.TT,
            counterparty_country="US",
        )
        self.second_case = TradeCase(
            "EXP-2",
            TradeDirection.EXPORT,
            "USD",
            Decimal("50000"),
            date(2026, 11, 1),
            PaymentMethod.TT,
            counterparty_country="DE",
        )
        self.program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Exporter", country_code="KR"),
            (self.export_case, self.second_case),
            as_of=date(2026, 7, 27),
        )
        self.assembler = EligibilityEvidenceAssembler(
            self.catalog,
            trusted_source_ids={"TRUSTED_COMPANY_SOURCE", "KSURE_CREDIT_SOURCE"},
        )

    def company_record(self, **changes) -> EligibilityEvidenceRecord:
        values = {
            "metadata": metadata("company:C1"),
            "company_id": "C1",
            "provider_key": "company_registry",
            "is_sme": True,
            "company_size": "small",
            "credit_issue_free": True,
        }
        values.update(changes)
        return CompanyQualificationEvidence(**values).to_record()

    def test_typed_models_map_exporter_and_importer_to_correct_scope(self) -> None:
        exporter = KsureCreditEvidence(
            metadata("ksure-exporter:C1", source_id="KSURE_CREDIT_SOURCE"),
            KsureCreditSubject.EXPORTER,
            "C1",
            "A",
            "ksure_credit",
        ).to_record()
        importer = KsureCreditEvidence(
            metadata(
                "ksure-importer:EXP-1",
                source_id="KSURE_CREDIT_SOURCE",
                content_hash=HASH_B,
            ),
            KsureCreditSubject.IMPORTER,
            "EXP-1",
            "B",
            "ksure_credit",
        ).to_record()

        self.assertIs(EvidenceSubjectKind.COMPANY, exporter.subject_kind)
        self.assertEqual({"company.ksure_exporter_grade": "A"}, exporter.facts)
        self.assertIs(EvidenceSubjectKind.CASE, importer.subject_kind)
        self.assertEqual(
            {"counterparty.ksure_importer_grade": "B"}, importer.facts
        )

    def test_company_evidence_fans_out_and_case_evidence_stays_scoped(self) -> None:
        importer = KsureCreditEvidence(
            metadata("ksure-importer:EXP-1", source_id="KSURE_CREDIT_SOURCE"),
            KsureCreditSubject.IMPORTER,
            "EXP-1",
            "B",
            "ksure_credit",
        ).to_record()
        result = self.assembler.assemble(
            program=self.program,
            records=(self.company_record(), importer),
            evaluated_at=MOMENT,
            required_fields_by_case={
                "EXP-1": ("company.size", "counterparty.ksure_importer_grade"),
                "EXP-2": ("company.size", "counterparty.ksure_importer_grade"),
            },
        )

        first = {item.field: item for item in result.assertions_by_case["EXP-1"]}
        second = {item.field: item for item in result.assertions_by_case["EXP-2"]}
        self.assertEqual("small", first["company.size"].value)
        self.assertEqual("small", second["company.size"].value)
        self.assertEqual("B", first["counterparty.ksure_importer_grade"].value)
        self.assertNotIn("counterparty.ksure_importer_grade", second)
        self.assertEqual((), result.missing_fields_by_case["EXP-1"])
        self.assertEqual(
            ("counterparty.ksure_importer_grade",),
            result.missing_fields_by_case["EXP-2"],
        )

    def test_output_is_directly_accepted_by_fact_assembler(self) -> None:
        result = self.assembler.assemble(
            program=self.program,
            records=(self.company_record(),),
            evaluated_at=MOMENT,
        )
        base = (
            EvidenceDescriptor(
                "trade:P1",
                EvidenceRole.USER_TRADE,
                ("EXP-1", "EXP-2"),
                generated_at=MOMENT,
            ),
            EvidenceDescriptor(
                "calculation:P1",
                EvidenceRole.CALCULATION,
                ("USD",),
                generated_at=MOMENT,
            ),
        )
        bundle = FactAssembler(self.catalog).assemble(
            program=self.program,
            case=self.export_case,
            assertions=result.assertions_by_case["EXP-1"],
            evidence=(*base, *result.evidence),
        )

        self.assertTrue(bundle.facts["company.is_sme"])
        self.assertEqual("small", bundle.facts["company.size"])
        self.assertEqual(
            ("company:C1",), bundle.evidence_ids_by_fact["company.size"]
        )

    def test_same_value_from_two_sources_preserves_both_evidence_ids(self) -> None:
        duplicate = replace(
            self.company_record(),
            metadata=metadata(
                "company:C1:second",
                source_id="KSURE_CREDIT_SOURCE",
                content_hash=HASH_B,
            ),
            provider_key="ksure_credit",
            facts={"company.size": "small"},
        )
        result = self.assembler.assemble(
            program=self.program,
            records=(self.company_record(), duplicate),
            evaluated_at=MOMENT,
        )
        assertion = next(
            item
            for item in result.assertions_by_case["EXP-1"]
            if item.field == "company.size"
        )
        self.assertEqual(("company:C1", "company:C1:second"), assertion.evidence_ids)

    def test_conflicting_fresh_evidence_is_not_silently_prioritized(self) -> None:
        conflict = replace(
            self.company_record(),
            metadata=metadata("company:C1:conflict", content_hash=HASH_B),
            facts={"company.size": "large"},
        )
        with self.assertRaisesRegex(FactContractError, "conflicting fresh evidence"):
            self.assembler.assemble(
                program=self.program,
                records=(self.company_record(), conflict),
                evaluated_at=MOMENT,
            )

    def test_stale_evidence_is_omitted_and_reported_as_missing(self) -> None:
        stale = self.company_record(
            metadata=metadata(
                "company:C1:stale",
                valid_until=MOMENT - timedelta(minutes=1),
            )
        )
        result = self.assembler.assemble(
            program=self.program,
            records=(stale,),
            evaluated_at=MOMENT,
            required_fields_by_case={"EXP-1": ("company.size",)},
        )

        self.assertEqual((), result.assertions_by_case["EXP-1"])
        self.assertEqual(("company.size",), result.missing_fields_by_case["EXP-1"])
        self.assertEqual(("company:C1:stale",), result.stale_evidence_ids)
        self.assertEqual((), result.evidence)
        self.assertEqual(1, len(result.unusable_evidence))
        self.assertEqual("stale", result.unusable_evidence[0].payload["usability"])
        self.assertNotIn("facts", result.unusable_evidence[0].payload)
        self.assertIn("rejected_facts", result.unusable_evidence[0].payload)

    def test_untrusted_future_wrong_subject_and_wrong_role_fail_closed(self) -> None:
        cases = (
            (
                replace(
                    self.company_record(),
                    metadata=metadata("untrusted", source_id="UNKNOWN_SOURCE"),
                ),
                "untrusted source_id",
            ),
            (
                replace(
                    self.company_record(),
                    metadata=replace(
                        metadata("future"),
                        observed_at=MOMENT + timedelta(minutes=1),
                        retrieved_at=MOMENT + timedelta(minutes=2),
                    ),
                ),
                "timestamp is in the future",
            ),
            (
                replace(self.company_record(), subject_id="OTHER"),
                "company subject does not match",
            ),
            (
                replace(
                    self.company_record(),
                    facts={"payment.is_netting": True},
                ),
                "cannot attest compliance fact",
            ),
        )
        for record, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(FactContractError, message):
                    self.assembler.assemble(
                        program=self.program,
                        records=(record,),
                        evaluated_at=MOMENT,
                    )

    def test_malformed_stale_fact_is_still_rejected(self) -> None:
        stale_bad = replace(
            self.company_record(
                metadata=metadata(
                    "stale-bad",
                    valid_until=MOMENT - timedelta(minutes=1),
                )
            ),
            facts={"company.is_sme": "true"},
        )
        with self.assertRaisesRegex(FactContractError, "expected boolean"):
            self.assembler.assemble(
                program=self.program,
                records=(stale_bad,),
                evaluated_at=MOMENT,
            )

    def test_metadata_requires_aware_ordered_times_and_canonical_hash(self) -> None:
        with self.assertRaisesRegex(ValueError, "must carry a time zone"):
            replace(metadata("naive"), observed_at=datetime(2026, 7, 27))
        with self.assertRaisesRegex(ValueError, "must not precede"):
            replace(
                metadata("reversed"),
                retrieved_at=MOMENT - timedelta(hours=3),
            )
        with self.assertRaisesRegex(ValueError, "canonical sha256"):
            replace(metadata("bad-hash"), content_hash="abc")

    def test_provider_registry_rejects_duplicate_keys_ids_and_mislabeling(self) -> None:
        record = self.company_record()
        registry = EligibilityProviderRegistry()
        registry.register(StaticProvider("company_registry", (record,)))
        with self.assertRaisesRegex(ValueError, "duplicate eligibility provider_key"):
            registry.register(StaticProvider("company_registry", ()))
        self.assertEqual((record,), registry.collect(program=self.program, evaluated_at=MOMENT))

        duplicate_ids = EligibilityProviderRegistry()
        duplicate_ids.register(StaticProvider("company_registry", (record, record)))
        with self.assertRaisesRegex(FactContractError, "duplicate evidence_id"):
            duplicate_ids.collect(program=self.program, evaluated_at=MOMENT)

        mislabeled = EligibilityProviderRegistry()
        mislabeled.register(StaticProvider("wrong", (record,)))
        with self.assertRaisesRegex(FactContractError, "does not match registry key"):
            mislabeled.collect(program=self.program, evaluated_at=MOMENT)


if __name__ == "__main__":
    unittest.main()
