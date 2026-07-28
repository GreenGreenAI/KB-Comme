"""§4.2[2]'s routing table, and the rule that a skip is never silent.

The table decides which workers get called. What these tests mostly defend is
the other half: a worker left out has to say what would put it back in, because
a compliance section that is quietly empty reads as "no filing due".
"""

import unittest
from datetime import date
from decimal import Decimal

from tradeflow.agent.intake import intake
from tradeflow.agent.routing import (
    COMPLIANCE,
    HEDGE,
    SUPPORT,
    WorkerDecision,
    derive_structure,
    known_structure,
    plan_execution,
)
from tradeflow.tools.exposure import analyze_exposure

AS_OF = date(2026, 7, 28)

EXPORT = {
    "direction": "수출",
    "amount": "100000",
    "expected_payment_date": "2026-10-24",
}
IMPORT = {
    "direction": "수입",
    "amount": "60000",
    "expected_payment_date": "2026-08-25",
}


def _plan(cases=None, **kwargs):
    program = intake(cases or [EXPORT, IMPORT], as_of=AS_OF).program
    return plan_execution(program, analyze_exposure(program), **kwargs)


class SkipContractTests(unittest.TestCase):
    def test_a_skip_without_a_reason_is_refused_at_construction(self) -> None:
        """Making the rule structural rather than a habit."""
        with self.assertRaises(ValueError):
            WorkerDecision("compliance", False)

        # A worker that runs needs no reason.
        WorkerDecision("compliance", True)


class ComplianceRoutingTests(unittest.TestCase):
    def test_an_undeclared_structure_keeps_compliance_out(self) -> None:
        plan = _plan()

        self.assertFalse(plan.runs(COMPLIANCE))

    def test_the_skip_reason_asks_rather_than_clears(self) -> None:
        """It must not be readable as 'no filing is due'."""
        reason = _plan().skipped()[COMPLIANCE]

        self.assertIn("알려주세요", reason)
        self.assertIn("신고 불필요로 판단하지 않습니다", reason)

    def test_a_known_structure_puts_compliance_in(self) -> None:
        plan = _plan(trade_structure={"trade.days_before_shipment": 400})

        self.assertTrue(plan.runs(COMPLIANCE))

    def test_a_structure_known_to_be_absent_still_counts(self) -> None:
        """"우리는 상계를 하지 않습니다" is an answer, not a blank.

        The rules turn it into 해당없음 with a reason, which is a result. Only
        an unestablished fact produces 정보부족.
        """
        self.assertEqual(
            ("payment.is_netting",),
            known_structure({"payment.is_netting": False}),
        )

    def test_an_unrelated_key_does_not_count_as_structure(self) -> None:
        self.assertEqual((), known_structure({"trade.currency": "USD"}))


class DerivedStructureTests(unittest.TestCase):
    """§5.5's period tests fall out of dates intake already collected."""

    def test_a_payment_long_before_shipment_is_derived(self) -> None:
        program = intake(
            [
                {
                    **EXPORT,
                    "expected_payment_date": "2026-08-25",
                    "expected_shipment_date": "2028-03-01",
                }
            ],
            as_of=AS_OF,
        ).program

        derived = derive_structure(program)

        self.assertEqual({"trade.days_before_shipment": 554}, derived)

    def test_an_import_derives_the_receipt_side(self) -> None:
        program = intake(
            [
                {
                    **IMPORT,
                    "expected_payment_date": "2026-08-25",
                    "expected_shipment_date": "2027-11-01",
                }
            ],
            as_of=AS_OF,
        ).program

        self.assertIn("trade.days_before_receipt", derive_structure(program))

    def test_no_shipment_date_derives_nothing(self) -> None:
        """A blank field must not be turned into a filing duty."""
        program = intake([EXPORT], as_of=AS_OF).program

        self.assertEqual({}, derive_structure(program))

    def test_payment_after_shipment_is_not_an_advance(self) -> None:
        program = intake(
            [
                {
                    **EXPORT,
                    "expected_payment_date": "2026-10-24",
                    "expected_shipment_date": "2026-09-01",
                }
            ],
            as_of=AS_OF,
        ).program

        self.assertEqual({}, derive_structure(program))

    def test_the_longest_gap_decides(self) -> None:
        """It is the one that can cross the one-year threshold."""
        program = intake(
            [
                {
                    **EXPORT,
                    "expected_payment_date": "2026-08-25",
                    "expected_shipment_date": "2026-10-01",
                },
                {
                    "direction": "수출",
                    "amount": "200000",
                    "expected_payment_date": "2026-08-25",
                    "expected_shipment_date": "2028-03-01",
                },
            ],
            as_of=AS_OF,
        ).program

        self.assertEqual(554, derive_structure(program)["trade.days_before_shipment"])

    def test_the_threshold_itself_is_left_to_the_rule(self) -> None:
        """Only the day count is produced; 365 lives in one place.

        Applying the limit here as well would let the two copies drift, and the
        rule is the one carrying the legal citation.
        """
        program = intake(
            [
                {
                    **EXPORT,
                    "expected_payment_date": "2026-08-25",
                    "expected_shipment_date": "2026-09-30",
                }
            ],
            as_of=AS_OF,
        ).program

        self.assertEqual({"trade.days_before_shipment": 36}, derive_structure(program))


class SupportRoutingTests(unittest.TestCase):
    def test_an_empty_profile_keeps_support_out(self) -> None:
        plan = _plan()

        self.assertFalse(plan.runs(SUPPORT))
        self.assertIn("기업규모", plan.skipped()[SUPPORT])

    def test_one_stated_company_fact_is_enough(self) -> None:
        plan = _plan(company_facts={"company.is_sme": True})

        self.assertTrue(plan.runs(SUPPORT))

    def test_a_profile_of_only_nulls_is_not_a_profile(self) -> None:
        plan = _plan(company_facts={"company.is_sme": None, "company.size": ""})

        self.assertFalse(plan.runs(SUPPORT))


class HedgeRoutingTests(unittest.TestCase):
    def _ready(self, **kwargs):
        return _plan(
            baseline_profit=Decimal("6000000"),
            profit_floor=Decimal("4000000"),
            has_usable_measure=True,
            **kwargs,
        )

    def test_a_hedgeable_position_is_planned(self) -> None:
        self.assertTrue(self._ready().runs(HEDGE))

    def test_a_fully_offset_position_needs_no_hedge(self) -> None:
        """§4.2[2]: run when net exposure is non-zero. Saying so is a result."""
        plan = _plan(
            cases=[EXPORT, {**IMPORT, "amount": "100000"}],
            baseline_profit=Decimal("6000000"),
            profit_floor=Decimal("4000000"),
            has_usable_measure=True,
        )

        self.assertFalse(plan.runs(HEDGE))
        self.assertIn("헤지할 금액이 없습니다", plan.skipped()[HEDGE])

    def test_a_missing_input_is_named_so_the_caller_can_ask_for_it(self) -> None:
        plan = _plan(has_usable_measure=True)

        self.assertFalse(plan.runs(HEDGE))
        self.assertEqual(("baseline_profit",), plan.requires())

    def test_the_floor_is_asked_for_only_after_the_baseline(self) -> None:
        plan = _plan(baseline_profit=Decimal("6000000"), has_usable_measure=True)

        self.assertEqual(("profit_floor",), plan.requires())

    def test_no_verified_measure_is_not_an_input_the_user_can_supply(self) -> None:
        """Nothing typed into the screen makes a priced product exist."""
        plan = _plan(
            baseline_profit=Decimal("6000000"), profit_floor=Decimal("4000000")
        )

        self.assertFalse(plan.runs(HEDGE))
        self.assertEqual((), plan.requires())


class PlanShapeTests(unittest.TestCase):
    def test_the_plan_reports_what_it_called(self) -> None:
        document = _plan(company_facts={"company.is_sme": True}).as_dict()

        self.assertEqual(["exposure", "market_scenario", "support"], document["planned"])
        self.assertEqual(5, len(document["workers"]))

    def test_exposure_and_market_are_always_planned(self) -> None:
        """§4.2[2]: 항상. Neither depends on anything beyond intake."""
        plan = _plan()

        self.assertTrue(plan.runs("exposure"))
        self.assertTrue(plan.runs("market_scenario"))
        self.assertFalse(plan.empty)


if __name__ == "__main__":
    unittest.main()
