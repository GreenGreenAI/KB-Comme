import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import EvidenceRole, PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.facts import (
    FactAssembler,
    FactAssertion,
    FactCatalog,
    FactContractError,
)

ROOT = Path(__file__).resolve().parents[2]


class FactAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json")
        self.assembler = FactAssembler(self.catalog)
        self.case = TradeCase(
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
            (self.case,),
            as_of=date(2026, 7, 27),
        )
        moment = datetime(2026, 7, 27, tzinfo=UTC)
        self.base_evidence = (
            EvidenceDescriptor(
                "trade:P1",
                EvidenceRole.USER_TRADE,
                ("EXP-1",),
                generated_at=moment,
            ),
            EvidenceDescriptor(
                "calculation:P1",
                EvidenceRole.CALCULATION,
                ("USD",),
                generated_at=moment,
            ),
            EvidenceDescriptor(
                "compliance:MA1",
                EvidenceRole.COMPLIANCE,
                ("EXP-1", "MA1"),
                generated_at=moment,
                payload={"facts": {"payment.uses_mutual_account": True}},
            ),
        )

    def test_core_facts_are_deterministic_and_usd_is_not_reconverted(self) -> None:
        bundle = self.assembler.assemble(
            program=self.program,
            case=self.case,
            assertions=(),
            evidence=self.base_evidence,
        )

        self.assertEqual("export", bundle.facts["trade.direction"])
        self.assertEqual("USD", bundle.facts["trade.currency"])
        self.assertEqual(
            Decimal("100000"), bundle.facts["trade.contract_amount_usd"]
        )
        self.assertTrue(bundle.facts["company.is_domestic"])
        self.assertEqual(
            ("calculation:P1",),
            bundle.evidence_ids_by_fact["trade.contract_amount_usd"],
        )

    def test_supplemental_fact_requires_catalog_role_evidence(self) -> None:
        with self.assertRaisesRegex(FactContractError, "requires compliance"):
            self.assembler.assemble(
                program=self.program,
                case=self.case,
                assertions=(
                    FactAssertion(
                        "payment.uses_mutual_account",
                        True,
                        ("trade:P1",),
                    ),
                ),
                evidence=self.base_evidence,
            )

    def test_matching_role_without_value_attestation_is_rejected(self) -> None:
        evidence = (
            *self.base_evidence[:2],
            EvidenceDescriptor(
                "compliance:empty",
                EvidenceRole.COMPLIANCE,
                ("EXP-1", "MA1"),
                generated_at=datetime(2026, 7, 27, tzinfo=UTC),
            ),
        )

        with self.assertRaisesRegex(FactContractError, "does not attest"):
            self.assembler.assemble(
                program=self.program,
                case=self.case,
                assertions=(
                    FactAssertion(
                        "payment.uses_mutual_account",
                        True,
                        ("compliance:empty",),
                    ),
                ),
                evidence=evidence,
            )

    def test_unknown_or_malformed_fact_is_rejected(self) -> None:
        for assertion, message in (
            (
                FactAssertion("unknown.fact", True, ("compliance:MA1",)),
                "unknown fact",
            ),
            (
                FactAssertion(
                    "payment.mutual_account.party_count",
                    "2",
                    ("compliance:MA1",),
                ),
                "expected integer",
            ),
        ):
            with self.subTest(field=assertion.field):
                with self.assertRaisesRegex(FactContractError, message):
                    self.assembler.assemble(
                        program=self.program,
                        case=self.case,
                        assertions=(assertion,),
                        evidence=self.base_evidence,
                    )

    def test_core_fact_cannot_be_overridden(self) -> None:
        with self.assertRaisesRegex(FactContractError, "cannot be overridden"):
            self.assembler.assemble(
                program=self.program,
                case=self.case,
                assertions=(
                    FactAssertion(
                        "trade.direction",
                        "import",
                        ("trade:P1",),
                    ),
                ),
                evidence=self.base_evidence,
            )

    def test_result_mappings_are_immutable(self) -> None:
        bundle = self.assembler.assemble(
            program=self.program,
            case=self.case,
            assertions=(),
            evidence=self.base_evidence,
        )

        with self.assertRaises(TypeError):
            bundle.facts["trade.direction"] = "import"


class CoreAttributeSafetyTests(unittest.TestCase):
    def test_program_rejects_duplicate_case_ids(self) -> None:
        first = TradeCase(
            "DUP",
            TradeDirection.EXPORT,
            "USD",
            Decimal("1"),
            date(2026, 9, 30),
            PaymentMethod.TT,
        )
        second = TradeCase(
            "DUP",
            TradeDirection.IMPORT,
            "USD",
            Decimal("1"),
            date(2026, 10, 1),
            PaymentMethod.TT,
        )

        with self.assertRaisesRegex(ValueError, "unique case_id"):
            TradeProgram(
                "P1",
                CompanyProfile("C1", "Exporter"),
                (first, second),
            )

    def test_trade_attributes_cannot_shadow_core_fact(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot override"):
            TradeCase(
                "EXP-1",
                TradeDirection.EXPORT,
                "USD",
                Decimal("1"),
                date(2026, 9, 30),
                PaymentMethod.TT,
                attributes={"trade.direction": "import"},
            )

    def test_company_attributes_cannot_shadow_core_fact(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot override"):
            CompanyProfile(
                "C1",
                "Exporter",
                attributes={"company.is_sme": False},
            )


if __name__ == "__main__":
    unittest.main()
