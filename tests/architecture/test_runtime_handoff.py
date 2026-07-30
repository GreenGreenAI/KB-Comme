import json
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.enums import (
    AvailabilityStatus,
    EvidenceRole,
    PaymentMethod,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.compliance_declarations import (
    ComplianceDeclarationAssembler,
    ComplianceGatewayDeclaration,
)
from tradeflow.knowledge.facts import FactCatalog
from tradeflow.knowledge.hedge_quotes import (
    HedgeQuoteSide,
    UserForwardQuote,
    UserQuoteHedgeAvailabilityService,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    ROOT
    / "knowledge"
    / "validation_suites"
    / "runtime_wiring_cases.json"
)


def _program(document: dict[str, object]) -> TradeProgram:
    return TradeProgram(
        document["program_id"],
        CompanyProfile(document["company_id"], document["company_name"]),
        tuple(
            TradeCase(
                item["case_id"],
                TradeDirection(item["direction"]),
                item["currency"],
                Decimal(item["amount"]),
                date.fromisoformat(item["expected_payment_date"]),
                PaymentMethod(item["payment_method"]),
            )
            for item in document["cases"]
        ),
        as_of=date.fromisoformat(document["as_of"]),
    )


def _declaration(document: dict[str, object]) -> ComplianceGatewayDeclaration:
    return ComplianceGatewayDeclaration(
        declaration_id=document["declaration_id"],
        company_id=document["company_id"],
        case_id=document["case_id"],
        declared_at=datetime.fromisoformat(document["declared_at"]),
        declared_by_role=document["declared_by_role"],
        confirmed=document["confirmed"],
        is_netting=document.get("is_netting"),
        is_third_party=document.get("is_third_party"),
        uses_mutual_account=document.get("uses_mutual_account"),
        uses_foreign_exchange_bank=document.get(
            "uses_foreign_exchange_bank"
        ),
    )


def _quote(document: dict[str, object]) -> UserForwardQuote:
    return UserForwardQuote(
        quote_id=document["quote_id"],
        provider_id=document["provider_id"],
        company_id=document["company_id"],
        case_ids=tuple(document["case_ids"]),
        base_currency=document["base_currency"],
        counter_currency=document["counter_currency"],
        side=HedgeQuoteSide(document["side"]),
        notional=Decimal(document["notional"]),
        contract_rate=Decimal(document["contract_rate"]),
        cost_rate=Decimal(document["cost_rate"]),
        settlement_date=date.fromisoformat(document["settlement_date"]),
        quoted_at=datetime.fromisoformat(document["quoted_at"]),
        valid_until=datetime.fromisoformat(document["valid_until"]),
        confirmed=document["confirmed"],
    )


class RuntimeHandoffGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.program = _program(cls.fixture["program"])
        cls.evaluated_at = datetime.fromisoformat(
            cls.fixture["evaluated_at"]
        )
        cls.declarations = ComplianceDeclarationAssembler(
            FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json")
        )

    def test_fixture_has_stable_identity_and_required_failure_cases(self) -> None:
        self.assertEqual("1.0", self.fixture["schema_version"])
        self.assertEqual("ROLE_B_USER_INPUT_WIRING", self.fixture["contract_id"])
        case_ids = {item["case_id"] for item in self.fixture["cases"]}
        self.assertEqual(
            {
                "ACTIVE_SELECTED_QUOTE",
                "NO_QUOTE",
                "QUOTE_NOT_SELECTED",
                "EXPIRED_QUOTE",
                "QUOTE_COMPANY_MISMATCH",
            },
            case_ids,
        )

    def test_domain_seams_produce_every_declared_golden_result(self) -> None:
        for item in self.fixture["cases"]:
            with self.subTest(case_id=item["case_id"]):
                declarations = self.declarations.assemble(
                    program=self.program,
                    declarations=tuple(
                        _declaration(value)
                        for value in item["declarations"]
                    ),
                    evaluated_at=self.evaluated_at,
                )
                quote_service = UserQuoteHedgeAvailabilityService(
                    tuple(_quote(value) for value in item["quotes"]),
                    evaluated_at=self.evaluated_at,
                    selected_quote_id=item["selected_quote_id"],
                )
                if "expected_error" in item:
                    with self.assertRaisesRegex(
                        ValueError,
                        item["expected_error"],
                    ):
                        quote_service.assemble(
                            program=self.program,
                            as_of=self.program.as_of,
                        )
                    continue

                quote_input = quote_service.assemble(
                    program=self.program,
                    as_of=self.program.as_of,
                )
                expected = item["expected"]
                fields = sorted(
                    assertion.field
                    for assertions in declarations.assertions_by_case.values()
                    for assertion in assertions
                )
                statuses = [
                    measure.status.value for measure in quote_input.measures
                ]
                roles = sorted(
                    evidence.role.value
                    for evidence in (
                        *declarations.evidence,
                        *quote_input.evidence,
                    )
                )
                may_execute = any(
                    measure.status is AvailabilityStatus.AVAILABLE
                    for measure in quote_input.measures
                )

                self.assertEqual(expected["declaration_fields"], fields)
                self.assertEqual(expected["measure_statuses"], statuses)
                self.assertEqual(sorted(expected["evidence_roles"]), roles)
                self.assertEqual(expected["may_execute_hedge"], may_execute)

    def test_fixture_evidence_roles_are_the_shared_contract_values(self) -> None:
        self.assertEqual("compliance", EvidenceRole.COMPLIANCE.value)
        self.assertEqual("market_data", EvidenceRole.MARKET_DATA.value)


if __name__ == "__main__":
    unittest.main()
