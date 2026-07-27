import unittest
from datetime import date
from decimal import Decimal

from tradeflow.agent.intake import intake
from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.tools.slots import MAX_QUESTIONS_PER_TURN, read_slots

COMPLETE = {
    "direction": "수출",
    "amount": "100000",
    "expected_payment_date": "2026-10-24",
}


class SlotReadingTests(unittest.TestCase):
    def test_mvp_defaults_are_filled_without_asking(self) -> None:
        reading = read_slots(COMPLETE)

        self.assertEqual("USD", reading.values["currency"])
        self.assertEqual("TT", reading.values["payment_method"])
        self.assertTrue(reading.complete)

    def test_korean_and_english_directions_both_read(self) -> None:
        for text in ("수출", "export", "EXPORT"):
            with self.subTest(text=text):
                self.assertEqual(
                    "export", read_slots({**COMPLETE, "direction": text}).values["direction"]
                )

    def test_amount_accepts_the_way_people_type_it(self) -> None:
        for text in ("100000", "100,000", "$100,000"):
            with self.subTest(text=text):
                self.assertEqual(
                    Decimal("100000"), read_slots({**COMPLETE, "amount": text}).values["amount"]
                )

    def test_date_accepts_common_separators(self) -> None:
        for text in ("2026-10-24", "2026/10/24", "2026.10.24"):
            with self.subTest(text=text):
                self.assertEqual(
                    date(2026, 10, 24),
                    read_slots({**COMPLETE, "expected_payment_date": text}).values[
                        "expected_payment_date"
                    ],
                )

    def test_unreadable_value_is_an_issue_not_a_missing_slot(self) -> None:
        """These need different answers: one asks again, the other corrects."""
        reading = read_slots({**COMPLETE, "amount": "대충 십만불"})

        self.assertEqual((), reading.missing)
        self.assertEqual(("amount",), tuple(i.field for i in reading.issues))
        self.assertFalse(reading.complete)

    def test_out_of_scope_currency_is_refused_with_a_reason(self) -> None:
        reading = read_slots({**COMPLETE, "currency": "EUR"})

        self.assertEqual(("currency",), tuple(i.field for i in reading.issues))
        self.assertIn("달러", reading.issues[0].reason)

    def test_advance_ratio_accepts_percent_or_fraction(self) -> None:
        for text, expected in (("30%", "0.30"), ("30", "0.30"), ("0.3", "0.3")):
            with self.subTest(text=text):
                value = read_slots({**COMPLETE, "advance_payment_ratio": text}).values[
                    "advance_payment_ratio"
                ]
                self.assertEqual(Decimal(expected), value)


class AskingPolicyTests(unittest.TestCase):
    def test_empty_input_asks_the_opening_question(self) -> None:
        result = intake([])

        self.assertFalse(result.ready)
        self.assertEqual(1, len(result.questions))

    def test_at_most_three_questions_per_turn(self) -> None:
        result = intake([{}])

        self.assertLessEqual(len(result.questions), MAX_QUESTIONS_PER_TURN)

    def test_amount_is_asked_before_date_before_direction(self) -> None:
        """These three unlock a result, so they come first and in this order."""
        questions = intake([{}]).questions

        self.assertIn("금액", questions[0])
        self.assertIn("날짜", questions[1])
        self.assertIn("수출", questions[2])

    def test_several_incomplete_cases_do_not_multiply_questions(self) -> None:
        result = intake([{}, {}, {}])

        self.assertLessEqual(len(result.questions), MAX_QUESTIONS_PER_TURN)

    def test_pipeline_does_not_proceed_while_a_slot_is_missing(self) -> None:
        result = intake([{"direction": "수출", "amount": "100000"}])

        self.assertFalse(result.ready)
        self.assertIsNone(result.program)
        self.assertEqual(("expected_payment_date",), result.missing)


class ProgramAssemblyTests(unittest.TestCase):
    def test_complete_input_produces_a_program(self) -> None:
        result = intake([COMPLETE], as_of=date(2026, 7, 26))

        self.assertTrue(result.ready)
        case = result.program.cases[0]
        self.assertEqual(TradeDirection.EXPORT, case.direction)
        self.assertEqual(Decimal("100000"), case.amount)
        self.assertEqual(PaymentMethod.TT, case.payment_method)

    def test_case_ids_reflect_direction(self) -> None:
        result = intake(
            [COMPLETE, {**COMPLETE, "direction": "수입", "amount": "60000"}],
            as_of=date(2026, 7, 26),
        )

        self.assertEqual(
            ["EXPORT-001", "IMPORT-002"], [c.case_id for c in result.program.cases]
        )

    def test_opening_balance_is_carried_into_the_program(self) -> None:
        result = intake(
            [COMPLETE], opening_balances={"usd": "20000"}, as_of=date(2026, 7, 26)
        )

        self.assertEqual(Decimal("20000"), result.program.opening_balances["USD"])

    def test_optional_details_ride_along_without_being_required(self) -> None:
        result = intake(
            [{**COMPLETE, "country": "US", "advance_payment_ratio": "30%"}],
            as_of=date(2026, 7, 26),
        )

        case = result.program.cases[0]
        self.assertTrue(result.ready)
        self.assertEqual("US", case.counterparty_country)
        self.assertEqual(Decimal("0.30"), case.attributes["advance_payment_ratio"])


if __name__ == "__main__":
    unittest.main()
