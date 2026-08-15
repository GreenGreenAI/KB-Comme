"""A sentence that continues the last one keeps what the last one established.

Each turn used to be read alone. 「왜?」 named no subject and described no
trade, so it fell through every reading to TRADE and the answer came back in
the default order — and the 상계 the company had declared a turn earlier
evaporated with the sentence that stated it.
"""

import unittest

from pydantic import ValidationError

from tradeflow.tools.utterance import payment_structure, withdrawn_structure
from tradeflow.tools.utterance_kind import (
    FOLLOW_UP,
    TRADE,
    UNCLEAR,
    asks_why,
    continues,
    read_kind,
)
from tradeflow.web.app import AnalyzeRequest, analyze_endpoint

CASE = {
    "direction": "수입",
    "amount": "60000",
    "expected_payment_date": "2026-08-25",
}
ASKED = "8월 25일 수입 6만 달러를 상계로 처리하는데 신고 대상인가요"


def _analyze(**extra) -> dict:
    return analyze_endpoint(
        AnalyzeRequest(cases=[CASE], as_of="2026-08-01", **extra)
    )["result"]


class FollowUpReadingTests(unittest.TestCase):
    def test_a_pointing_sentence_is_not_a_trade_description(self) -> None:
        for said in ("왜?", "그럼?", "더 자세히", "그거 얼마야?"):
            with self.subTest(said=said):
                self.assertEqual(
                    FOLLOW_UP, read_kind(said, heard={}, topics=())
                )

    def test_a_sentence_that_names_its_own_subject_is_not_a_follow_up(self) -> None:
        """「그럼 신고는?」 points and names. A sentence that says what it is
        about does not need the last one to say it."""
        self.assertNotEqual(
            FOLLOW_UP, read_kind("그럼 신고는?", heard={}, topics=("compliance",))
        )

    def test_an_unrecognised_sentence_is_not_mistaken_for_a_follow_up(self) -> None:
        """The follow-up list is short on purpose. A sentence wrongly read as
        one inherits an order it never asked for — and one that is simply
        unrecognised says that instead of claiming to be a trade."""
        self.assertEqual(UNCLEAR, read_kind("음", heard={}, topics=()))

    def test_only_some_follow_ups_have_reasons_waiting(self) -> None:
        self.assertTrue(asks_why("왜?"))
        self.assertTrue(continues("그럼?"))
        self.assertFalse(asks_why("그럼?"))


class SubjectCarriesTests(unittest.TestCase):
    def test_a_follow_up_is_ordered_by_the_last_question(self) -> None:
        after = _analyze(utterance="왜?", asked_about=ASKED)
        alone = _analyze(utterance="왜?")

        self.assertEqual("compliance", after["execution_plan"]["section_order"][0])
        self.assertNotEqual("compliance", alone["execution_plan"]["section_order"][0])

    def test_the_older_sentence_never_supplies_facts(self) -> None:
        """Ordering only. A sentence already answered must not describe its
        trade a second time — `asked_about` reaches `read_intent` and stops."""
        body = analyze_endpoint(
            AnalyzeRequest(
                cases=[CASE],
                as_of="2026-08-01",
                utterance="왜?",
                asked_about="12월 3일 수출 15만 달러 받기로 했어요",
            )
        )

        self.assertEqual(1, len(body["result"]["trade_timeline"]))
        self.assertEqual("import", body["result"]["trade_timeline"][0]["direction"])


class DeclaredStructureCarriesTests(unittest.TestCase):
    def test_a_declaration_survives_the_next_sentence(self) -> None:
        carried = _analyze(
            utterance="왜?",
            asked_about=ASKED,
            declared_structure={"payment.is_netting": True},
        )

        self.assertEqual({"payment.is_netting": True}, carried["declared_structure"])
        self.assertTrue(carried["because"])

    def test_the_company_can_take_it_back(self) -> None:
        """Once a declaration travels between turns there has to be a way to
        correct it, or a misreading is permanent for the rest of the
        conversation."""
        corrected = _analyze(
            utterance="상계는 아닙니다",
            declared_structure={"payment.is_netting": True},
        )

        self.assertEqual({}, corrected["declared_structure"])

    def test_taking_back_is_not_denying(self) -> None:
        """Dropping moves the answer to 「모릅니다」, which is a question the
        company can answer. §5.5 refuses to conclude 신고 불필요 from silence,
        and asserting False here would be that conclusion wearing a fact."""
        self.assertEqual({}, payment_structure("상계는 아닙니다"))
        self.assertEqual(
            frozenset({"payment.is_netting"}), withdrawn_structure("상계는 아닙니다")
        )

    def test_a_correction_that_names_the_right_one_lands_both_ways(self) -> None:
        both = _analyze(
            utterance="상계가 아니라 상호계산입니다",
            declared_structure={"payment.is_netting": True},
        )

        self.assertEqual(
            {"payment.uses_mutual_account": True}, both["declared_structure"]
        )

    def test_a_caller_cannot_declare_a_field_no_sentence_can(self) -> None:
        """The fact catalog is wider than what §5.5's reader produces, and a
        field no sentence can state must not become one a request body can."""
        with self.assertRaises(ValidationError):
            AnalyzeRequest(declared_structure={"company.is_sme": True})


if __name__ == "__main__":
    unittest.main()
