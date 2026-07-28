import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tradeflow.domain.enums import (
    AvailabilityStatus,
    PaymentMethod,
    TradeDirection,
)
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.facts import FactContractError
from tradeflow.knowledge.hedge_quotes import (
    HedgeQuoteSide,
    UserForwardQuote,
    UserQuoteHedgeAvailabilityService,
)


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 28, 10, tzinfo=KST)
SETTLEMENT = date(2026, 10, 31)


class UserQuoteHedgeAvailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Exporter"),
            (
                TradeCase(
                    "EXP-1",
                    TradeDirection.EXPORT,
                    "USD",
                    Decimal("100000"),
                    SETTLEMENT,
                    PaymentMethod.TT,
                ),
            ),
            as_of=NOW.date(),
        )

    def quote(self, **changes: object) -> UserForwardQuote:
        values: dict[str, object] = {
            "quote_id": "Q-100",
            "provider_id": "KB",
            "company_id": "C1",
            "case_ids": ("EXP-1",),
            "base_currency": "USD",
            "counter_currency": "KRW",
            "side": HedgeQuoteSide.SELL,
            "notional": Decimal("100000"),
            "contract_rate": Decimal("1482"),
            "cost_rate": Decimal("0.001"),
            "settlement_date": SETTLEMENT,
            "quoted_at": NOW - timedelta(minutes=5),
            "valid_until": NOW + timedelta(minutes=5),
            "confirmed": True,
        }
        values.update(changes)
        return UserForwardQuote(**values)

    def service(
        self,
        *quotes: UserForwardQuote,
        selected: str | None = "Q-100",
    ) -> UserQuoteHedgeAvailabilityService:
        return UserQuoteHedgeAvailabilityService(
            quotes,
            evaluated_at=NOW,
            selected_quote_id=selected,
        )

    def test_selected_active_exact_quote_is_available_and_auditable(self) -> None:
        result = self.service(self.quote()).assemble(
            program=self.program,
            as_of=NOW.date(),
        )

        self.assertEqual(1, len(result.measures))
        measure = result.measures[0]
        self.assertIs(measure.status, AvailabilityStatus.AVAILABLE)
        self.assertEqual(Decimal("1482"), measure.contract_rate)
        self.assertEqual(Decimal("0.001"), measure.cost_rate)
        self.assertEqual(("USER_QUOTE:KB:Q-100",), measure.source_ids)
        self.assertEqual(
            "Q-100",
            result.quote_ids_by_measure[measure.measure_id],
        )

        descriptor = result.evidence[0]
        self.assertEqual(("USER_QUOTE:KB:Q-100",), descriptor.source_ids)
        self.assertEqual("market_data", descriptor.role.value)
        self.assertEqual("2026-07-28T10:05:00+09:00", descriptor.payload["valid_until"])
        self.assertIn(
            "not_provider_verified",
            descriptor.payload["limitations"],
        )

    def test_no_quote_is_information_gap_not_availability(self) -> None:
        result = self.service(selected=None).assemble(
            program=self.program,
            as_of=NOW.date(),
        )

        self.assertEqual((), result.evidence)
        self.assertIs(
            result.measures[0].status,
            AvailabilityStatus.INSUFFICIENT_INFORMATION,
        )
        self.assertIsNone(result.measures[0].contract_rate)

    def test_quote_must_be_explicitly_selected(self) -> None:
        result = self.service(self.quote(), selected=None).assemble(
            program=self.program,
            as_of=NOW.date(),
        )

        self.assertIs(
            result.measures[0].status,
            AvailabilityStatus.CONDITIONAL,
        )
        self.assertTrue(
            any("선택" in reason for reason in result.measures[0].status_reasons)
        )

    def test_linked_import_and_export_use_residual_at_latest_maturity(self) -> None:
        import_case = TradeCase(
            "IMP-1",
            TradeDirection.IMPORT,
            "USD",
            Decimal("60000"),
            date(2026, 8, 31),
            PaymentMethod.TT,
        )
        linked = replace(
            self.program,
            cases=(import_case, *self.program.cases),
        )
        quote = self.quote(
            case_ids=("IMP-1", "EXP-1"),
            notional=Decimal("40000"),
        )

        measure = self.service(quote).evaluate_measures(
            program=linked,
            as_of=NOW.date(),
        )[0]

        self.assertIs(measure.status, AvailabilityStatus.AVAILABLE)

    def test_expired_quote_is_unavailable_but_remains_audit_evidence(self) -> None:
        expired = self.quote(valid_until=NOW - timedelta(seconds=1))
        result = self.service(expired).assemble(
            program=self.program,
            as_of=NOW.date(),
        )

        self.assertIs(
            result.measures[0].status,
            AvailabilityStatus.UNAVAILABLE,
        )
        self.assertTrue(
            any("만료" in reason for reason in result.measures[0].status_reasons)
        )
        self.assertEqual(1, len(result.evidence))

        unselected = self.service(expired, selected=None).assemble(
            program=self.program,
            as_of=NOW.date(),
        )
        self.assertIs(
            unselected.measures[0].status,
            AvailabilityStatus.UNAVAILABLE,
        )

    def test_scope_side_maturity_notional_and_pair_fail_closed(self) -> None:
        other_case = TradeCase(
            "EXP-2",
            TradeDirection.EXPORT,
            "USD",
            Decimal("1000"),
            SETTLEMENT,
            PaymentMethod.TT,
        )
        two_case_program = replace(
            self.program,
            cases=(*self.program.cases, other_case),
        )
        cases = (
            (self.quote(side=HedgeQuoteSide.BUY), self.program, "방향"),
            (
                self.quote(notional=Decimal("99999")),
                self.program,
                "명목금액",
            ),
            (
                self.quote(settlement_date=date(2026, 11, 1)),
                self.program,
                "결제일",
            ),
            (
                self.quote(counter_currency="JPY"),
                self.program,
                "원화",
            ),
            (
                self.quote(),
                two_case_program,
                "모든 거래",
            ),
        )
        for quote, program, reason_fragment in cases:
            with self.subTest(reason=reason_fragment):
                measure = self.service(quote).evaluate_measures(
                    program=program,
                    as_of=NOW.date(),
                )[0]
                self.assertIs(
                    measure.status,
                    AvailabilityStatus.UNAVAILABLE,
                )
                self.assertTrue(
                    any(
                        reason_fragment in reason
                        for reason in measure.status_reasons
                    )
                )

    def test_company_future_unknown_case_and_date_mismatch_are_rejected(self) -> None:
        invalid = (
            (self.quote(company_id="OTHER"), "company does not match"),
            (
                self.quote(quoted_at=NOW + timedelta(seconds=1)),
                "in the future",
            ),
            (self.quote(case_ids=("MISSING",)), "unknown cases"),
        )
        for quote, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex(FactContractError, message):
                    self.service(quote).assemble(
                        program=self.program,
                        as_of=NOW.date(),
                    )

        with self.assertRaisesRegex(FactContractError, "as_of date"):
            self.service(self.quote()).assemble(
                program=self.program,
                as_of=NOW.date() - timedelta(days=1),
            )

    def test_quote_contract_rejects_ambiguous_or_impossible_values(self) -> None:
        invalid = (
            ({"confirmed": False}, "explicitly confirmed"),
            ({"contract_rate": Decimal("0")}, "contract_rate"),
            ({"notional": Decimal("0")}, "notional"),
            ({"cost_rate": Decimal("-0.1")}, "cost_rate"),
            ({"case_ids": ()}, "case_ids"),
            ({"provider_id": "bad provider"}, "provider_id"),
            ({"side": "sell"}, "side"),
            ({"contract_rate": 1482.0}, "Decimal"),
        )
        for changes, message in invalid:
            with self.subTest(message=message):
                with self.assertRaisesRegex((ValueError, TypeError), message):
                    self.quote(**changes)

    def test_duplicate_and_unknown_selection_are_rejected(self) -> None:
        with self.assertRaisesRegex(FactContractError, "duplicate"):
            self.service(self.quote(), self.quote())
        with self.assertRaisesRegex(FactContractError, "does not exist"):
            UserQuoteHedgeAvailabilityService(
                (self.quote(),),
                evaluated_at=NOW,
                selected_quote_id="OTHER",
            )


if __name__ == "__main__":
    unittest.main()
