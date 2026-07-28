import json
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.enums import (
    DecisionStatus,
    Freshness,
    PaymentMethod,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.compliance_declarations import (
    DECLARABLE_GATEWAY_FIELDS,
    USER_DECLARATION_SOURCE_ID,
    ComplianceDeclarationAssembler,
    ComplianceGatewayDeclaration,
)
from tradeflow.knowledge.facts import FactAssembler, FactCatalog, FactContractError
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)
RULEPACK_PATH = ROOT / "knowledge" / "rulepacks" / "fx_compliance_mvp.json"


class ComplianceDeclarationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json")
        cls.assembler = ComplianceDeclarationAssembler(cls.catalog)
        cls.knowledge = KnowledgeRepository.from_json(
            ROOT / "knowledge" / "source_registry.json",
            RULEPACK_PATH,
        )
        cls.pipeline = TradeFlowPipeline(
            cls.knowledge,
            fact_assembler=FactAssembler(cls.catalog),
        )
        cls.freshness = {
            source_id: Freshness.FRESH for source_id in cls.knowledge.sources
        }
        raw_rules = json.loads(RULEPACK_PATH.read_text(encoding="utf-8"))["rules"]
        cls.gateway_rule_ids = {
            rule["rule_id"]
            for rule in raw_rules
            if any(
                condition["field"] in DECLARABLE_GATEWAY_FIELDS
                for condition in rule["conditions"]
            )
        }
        cls.netting_rule_ids = {
            rule["rule_id"]
            for rule in raw_rules
            if any(
                condition["field"] == "payment.is_netting"
                for condition in rule["conditions"]
            )
        }

    def setUp(self) -> None:
        cases = (
            TradeCase(
                "EXP-1",
                TradeDirection.EXPORT,
                "USD",
                Decimal("100000"),
                date(2026, 9, 30),
                PaymentMethod.TT,
            ),
            TradeCase(
                "IMP-1",
                TradeDirection.IMPORT,
                "JPY",
                Decimal("5000000"),
                date(2026, 10, 15),
                PaymentMethod.TT,
            ),
        )
        self.program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Exporter", country_code="KR"),
            cases,
            as_of=NOW.date(),
        )

    def declaration(self, **changes: object) -> ComplianceGatewayDeclaration:
        values: dict[str, object] = {
            "declaration_id": "DECL-1",
            "company_id": "C1",
            "case_id": "EXP-1",
            "declared_at": NOW,
            "declared_by_role": "trade_manager",
            "confirmed": True,
            "is_netting": False,
            "is_third_party": False,
            "uses_mutual_account": False,
            "uses_foreign_exchange_bank": True,
        }
        values.update(changes)
        return ComplianceGatewayDeclaration(**values)

    def test_declaration_is_case_scoped_and_source_is_explicit(self) -> None:
        assembled = self.assembler.assemble(
            program=self.program,
            declarations=(self.declaration(),),
            evaluated_at=NOW,
        )

        self.assertEqual(4, len(assembled.assertions_by_case["EXP-1"]))
        self.assertEqual((), assembled.assertions_by_case["IMP-1"])
        descriptor = assembled.evidence[0]
        self.assertEqual((USER_DECLARATION_SOURCE_ID,), descriptor.source_ids)
        self.assertEqual("compliance", descriptor.role.value)
        self.assertEqual("case", descriptor.payload["scope"])
        self.assertEqual(
            {
                "scope_gate_only",
                "not_legal_interpretation",
                "not_filing_exemption",
            },
            set(descriptor.payload["limitations"]),
        )

    def test_negative_gates_narrow_rules_out_in_real_pipeline(self) -> None:
        assembled = self.assembler.assemble(
            program=self.program,
            declarations=(self.declaration(),),
            evaluated_at=NOW,
        )
        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case=assembled.assertions_by_case,
            evidence=assembled.evidence,
            source_freshness=self.freshness,
        )

        decisions = [
            item
            for item in packet.decisions
            if item.subject_id == "EXP-1" and item.rule_id in self.gateway_rule_ids
        ]
        self.assertTrue(decisions)
        self.assertTrue(
            all(item.status is DecisionStatus.NOT_ELIGIBLE for item in decisions)
        )
        self.assertTrue(all(item.matched is False for item in decisions))
        self.assertFalse(
            any(action.subject_id == "EXP-1" for action in packet.actions)
        )
        declaration_evidence = next(
            item
            for item in packet.evidence
            if item.evidence_id == "declaration:DECL-1"
        )
        self.assertEqual(
            (USER_DECLARATION_SOURCE_ID,),
            declaration_evidence.source_ids,
        )

    def test_positive_gate_does_not_infer_downstream_legal_facts(self) -> None:
        declaration = self.declaration(
            is_netting=True,
            is_third_party=None,
            uses_mutual_account=None,
            uses_foreign_exchange_bank=None,
        )
        assembled = self.assembler.assemble(
            program=self.program,
            declarations=(declaration,),
            evaluated_at=NOW,
        )
        packet = self.pipeline.analyze_case_packet(
            self.program,
            assertions_by_case=assembled.assertions_by_case,
            evidence=assembled.evidence,
            source_freshness=self.freshness,
        )

        decisions = [
            item
            for item in packet.decisions
            if item.subject_id == "EXP-1" and item.rule_id in self.netting_rule_ids
        ]
        self.assertTrue(decisions)
        self.assertTrue(
            all(
                item.status is DecisionStatus.INSUFFICIENT_INFORMATION
                for item in decisions
            )
        )
        self.assertTrue(all(item.missing_fields for item in decisions))
        case_inputs = dict(
            dict(
                next(item.value for item in packet.inputs if item.name == "cases")
            )["EXP-1"]
        )
        self.assertNotIn("payment.netting.exception_category", case_inputs)

    def test_invalid_scope_time_and_confirmation_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be confirmed"):
            self.declaration(confirmed=False)

        invalid = (
            (self.declaration(company_id="OTHER"), "company does not match"),
            (self.declaration(case_id="OTHER"), "unknown case"),
            (
                self.declaration(declared_at=NOW + timedelta(seconds=1)),
                "in the future",
            ),
        )
        for declaration, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(FactContractError, message):
                    self.assembler.assemble(
                        program=self.program,
                        declarations=(declaration,),
                        evaluated_at=NOW,
                    )

    def test_duplicate_active_declarations_fail_closed(self) -> None:
        second = replace(self.declaration(), declaration_id="DECL-2")
        with self.assertRaisesRegex(FactContractError, "one active"):
            self.assembler.assemble(
                program=self.program,
                declarations=(self.declaration(), second),
                evaluated_at=NOW,
            )

    def test_allowlist_excludes_exceptions_filings_and_deadlines(self) -> None:
        self.assertEqual(
            {
                "payment.is_netting",
                "payment.is_third_party",
                "payment.uses_mutual_account",
                "payment.uses_foreign_exchange_bank",
            },
            set(DECLARABLE_GATEWAY_FIELDS),
        )
        self.assertFalse(
            any(
                token in field
                for field in DECLARABLE_GATEWAY_FIELDS
                for token in ("exception", "completed", "deadline")
            )
        )


if __name__ == "__main__":
    unittest.main()
