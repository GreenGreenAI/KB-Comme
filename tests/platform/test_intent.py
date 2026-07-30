"""§4.2[2]'s third input: what the sentence is asking about.

The property these tests exist for is the one that is easy to get wrong in the
obvious direction. A router that answers only the question asked is the normal
shape for a multi-agent product, and it is the wrong shape here: §2's user does
not know their own exposure, so the sections they did not ask about are exactly
the ones they need. Intent may reorder. It may not remove.
"""

import unittest
from datetime import date
from decimal import Decimal

from tradeflow.agent.intake import intake
from tradeflow.agent.routing import plan_execution
from tradeflow.tools.exposure import analyze_exposure
from tradeflow.tools.intent import (
    DEFAULT_ORDER,
    describe,
    read_intent,
    section_order,
)

AS_OF = date(2026, 7, 28)
CASES = [
    {"direction": "수출", "amount": "100000", "expected_payment_date": "2026-10-24"},
    {"direction": "수입", "amount": "60000", "expected_payment_date": "2026-08-25"},
]


class ReadingTests(unittest.TestCase):
    def test_a_trade_description_asks_nothing(self) -> None:
        """Most sessions open with a statement, not a question."""
        self.assertEqual(
            (), read_intent("10월 24일에 수출대금 10만 달러 받기로 했어요")
        )

    def test_each_section_is_recognised_by_the_words_a_company_uses(self) -> None:
        for sentence, topic in (
            ("환율이 얼마나 움직일까요?", "market_scenario"),
            ("헤지를 얼마나 해야 하나요?", "hedge"),
            ("자금이 얼마나 필요한가요?", "exposure"),
            ("쓸 수 있는 보증이나 보험이 있나요?", "support"),
            ("신고해야 할 게 있나요?", "compliance"),
        ):
            with self.subTest(sentence=sentence):
                self.assertIn(topic, read_intent(sentence))

    def test_money_the_company_needs_is_not_money_it_is_owed(self) -> None:
        """"제작에 들어갈 자금이 부족합니다" is a question about raising money.

        Bare 자금 sat in `exposure`, and because intent is ordered by where a
        topic first appears, it beat the 정책자금 at the end of the sentence.
        The whole answer then came back about exchange-rate exposure, and asked
        for the amount and date that calculation wanted — to a company that had
        asked which loan it could get.
        """
        intent = read_intent(
            "베트남에 3억 원 규모 장비를 수출하는데 제품 제작에 들어갈 자금이 "
            "부족합니다. 중소기업이 쓸 수 있는 무역금융이나 정책자금이 있을까요?"
        )

        self.assertEqual(("support",), intent)

    def test_a_sentence_may_ask_about_several_things(self) -> None:
        intent = read_intent("환율 때문에 손해 볼까 걱정인데 헤지가 필요할까요?")

        self.assertIn("market_scenario", intent)
        self.assertIn("hedge", intent)

    def test_topics_come_back_in_the_order_the_sentence_raises_them(self) -> None:
        self.assertEqual(
            ("compliance", "market_scenario"),
            read_intent("신고 의무부터 보고 환율도 알려주세요"),
        )

    def test_a_substring_is_not_a_topic(self) -> None:
        """"막을 방법" is not a question about statutes.

        Korean compounds have no space to anchor a match on, so a bare 법 read
        the word 방법 as a filing question and pushed compliance to the top of
        an answer about hedging.
        """
        self.assertNotIn(
            "compliance", read_intent("환율 손해를 막을 방법이 있나요?")
        )

    def test_an_empty_sentence_reads_as_no_question(self) -> None:
        self.assertEqual((), read_intent(None))
        self.assertEqual((), read_intent("   "))


class OrderingTests(unittest.TestCase):
    def test_nothing_asked_keeps_the_default_order(self) -> None:
        self.assertEqual(DEFAULT_ORDER, section_order(()))

    def test_the_topic_asked_about_comes_first(self) -> None:
        self.assertEqual("compliance", section_order(("compliance",))[0])

    def test_no_section_is_ever_dropped(self) -> None:
        """The property this module exists to preserve."""
        for intent in ((), ("hedge",), ("compliance", "market_scenario")):
            with self.subTest(intent=intent):
                self.assertEqual(
                    set(DEFAULT_ORDER), set(section_order(intent))
                )
                self.assertEqual(
                    len(DEFAULT_ORDER), len(section_order(intent))
                )

    def test_unasked_sections_keep_their_order_behind_the_asked_ones(self) -> None:
        order = section_order(("hedge",))

        self.assertEqual("hedge", order[0])
        self.assertEqual(
            ["exposure", "market_scenario", "support", "compliance"],
            list(order[1:]),
        )

    def test_a_topic_named_twice_is_not_duplicated(self) -> None:
        order = section_order(("hedge", "hedge"))

        self.assertEqual(len(DEFAULT_ORDER), len(order))

    def test_the_response_can_say_that_it_reordered(self) -> None:
        self.assertFalse(describe(())["reordered"])
        self.assertTrue(describe(("hedge",))["reordered"])


class PlanIsNotNarrowedTests(unittest.TestCase):
    """Intent must not subtract from the call plan.

    Asking about the exchange rate does not stop this company having a filing
    duty, and a plan cut down to the question would withhold precisely what the
    user did not know to ask for.
    """

    def _plan(self, intent):
        program = intake(CASES, as_of=AS_OF).program
        return plan_execution(
            program,
            analyze_exposure(program),
            company_facts={"company.is_sme": True},
            trade_structure={"trade.days_before_shipment": 400},
            baseline_profit=Decimal("6000000"),
            profit_floor=Decimal("4000000"),
            has_usable_measure=True,
            intent=intent,
        )

    def test_asking_about_one_section_still_plans_every_worker(self) -> None:
        planned = self._plan(("market_scenario",)).as_dict()["planned"]

        self.assertEqual(self._plan(()).as_dict()["planned"], planned)

    def test_asking_about_the_rate_still_plans_compliance(self) -> None:
        self.assertTrue(self._plan(("market_scenario",)).runs("compliance"))

    def test_the_plan_carries_the_intent_it_was_given(self) -> None:
        document = self._plan(("hedge",)).as_dict()

        self.assertEqual(["hedge"], document["topics"])
        self.assertEqual("hedge", document["section_order"][0])


if __name__ == "__main__":
    unittest.main()
