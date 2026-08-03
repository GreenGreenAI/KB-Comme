import unittest

from tradeflow.runtime import asking


def _short(field: str, title: str = "K-SURE 단기수출보험") -> dict:
    return {
        "title": title,
        "status": "insufficient_information",
        "missing_fields": [field],
    }


class AskableTests(unittest.TestCase):
    """Which missing facts become questions, and which never do."""

    RESULT = {
        "support_candidates": [
            {
                "title": "K-SURE 단기수출보험(선적후·개별)",
                "status": "insufficient_information",
                "missing_fields": [
                    "company.ksure_exporter_grade",
                    "counterparty.country_restricted",
                    "trade.payment_term_days",
                ],
            }
        ]
    }

    def test_a_fact_we_look_up_is_never_put_to_the_company(self) -> None:
        """Asking a company whether its buyer's country is on K-SURE's
        restricted list is asking them to make our judgement, and their answer
        would be evidence of nothing."""
        asked = [item["field"] for item in asking.questions(self.RESULT)]

        self.assertNotIn("counterparty.country_restricted", asked)

    def test_a_fact_we_compute_is_asked_for_by_its_input(self) -> None:
        """Never for the value. A payment term the company typed could
        disagree with the dates beside it on screen, and nothing would say
        which one the rule used — so the question is the shipment date, and
        the subtraction stays ours."""
        asked = asking.questions(self.RESULT)
        term = next(item for item in asked if item["field"] != "company.ksure_exporter_grade")

        self.assertEqual("expected_shipment_date", term["field"])
        self.assertEqual("case", term["answer_as"])
        self.assertEqual("date", term["kind"])
        self.assertNotIn(
            "trade.payment_term_days", [item["field"] for item in asked]
        )

    def test_a_derived_question_names_the_trade_it_is_about(self) -> None:
        """The judgement names its own subject. Without it the screen wrote
        every slot answer onto the last trade described — so a company with an
        export and an import answered 「언제 선적하시나요」 onto the import, the
        export's term still did not derive, and the same question came back on
        every turn after that."""
        result = {
            "support_candidates": [
                {
                    "title": "K-SURE 단기수출보험(선적후·개별)",
                    "subject_id": "EXPORT-001",
                    "status": "insufficient_information",
                    "missing_fields": ["trade.payment_term_days"],
                }
            ]
        }

        asked = asking.questions(result)[0]

        self.assertEqual("EXPORT-001", asked["case_id"])
        self.assertEqual("expected_shipment_date", asked["field"])

    def test_a_slot_already_given_is_not_asked_for_again(self) -> None:
        """A derived fact can legitimately fail to derive: a payment landing
        before shipment is a prepayment, and no term comes out of it. Without
        this floor the rule keeps reporting the fact missing and the screen
        keeps asking someone who has already answered."""
        result = {
            "support_candidates": [
                {
                    "title": "K-SURE 단기수출보험(선적후·개별)",
                    "subject_id": "EXPORT-001",
                    "status": "insufficient_information",
                    "missing_fields": ["trade.payment_term_days"],
                }
            ]
        }

        self.assertEqual(
            [],
            asking.questions(
                result, supplied=frozenset({("EXPORT-001", "expected_shipment_date")})
            ),
        )

    def test_another_trades_answer_does_not_count(self) -> None:
        self.assertEqual(
            1,
            len(
                asking.questions(
                    {
                        "support_candidates": [
                            {
                                "title": "단기수출보험",
                                "subject_id": "EXPORT-001",
                                "status": "insufficient_information",
                                "missing_fields": ["trade.payment_term_days"],
                            }
                        ]
                    },
                    supplied=frozenset(
                        {("IMPORT-002", "expected_shipment_date")}
                    ),
                )
            ),
        )

    def test_a_judgement_that_reached_a_verdict_is_not_asked_about(self) -> None:
        settled = {
            "support_candidates": [
                {
                    "title": "K-SURE 환변동보험",
                    "status": "expert_confirmation_required",
                    "missing_fields": ["company.ksure_exporter_grade"],
                }
            ]
        }

        self.assertEqual([], asking.questions(settled))

    def test_two_rules_wanting_the_same_fact_ask_once(self) -> None:
        """Being asked for the same grade twice says the screen is not reading
        its own answers."""
        result = {
            "support_candidates": [
                _short("company.ksure_exporter_grade", "A"),
                _short("company.ksure_exporter_grade", "B"),
            ]
        }

        self.assertEqual(1, len(asking.questions(result)))

    def test_what_was_answered_is_not_asked_again(self) -> None:
        result = {"support_candidates": [_short("company.ksure_exporter_grade")]}

        self.assertEqual(
            [],
            asking.questions(
                result, already={"company.ksure_exporter_grade": "C"}
            ),
        )

    def test_the_question_says_which_judgement_it_opens(self) -> None:
        """A question with no stated purpose reads as a form. The same question
        under the name of the product it unlocks is an offer."""
        result = {"support_candidates": [_short("financing.purpose", "수출신용보증")]}

        self.assertEqual("수출신용보증", asking.questions(result)[0]["opens"])

    def test_the_answers_on_offer_come_from_the_catalog(self) -> None:
        """Not from a list written here. The allowed values are the rules', and
        a second copy of them would drift the first time one changed."""
        result = {"support_candidates": [_short("financing.has_bank_consultation")]}

        options = asking.questions(result)[0]["options"]

        self.assertEqual(["true", "false"], [item["value"] for item in options])
        self.assertTrue(all(item["label"] for item in options))


class AcceptanceTests(unittest.TestCase):
    def test_a_value_the_rules_would_reject_is_refused_here(self) -> None:
        self.assertTrue(asking.accepts("company.ksure_exporter_grade", "C"))
        self.assertFalse(asking.accepts("company.ksure_exporter_grade", "Z"))
        self.assertTrue(asking.accepts("financing.has_bank_consultation", "true"))
        self.assertFalse(asking.accepts("financing.has_bank_consultation", "네"))

    def test_a_field_outside_the_askable_set_is_never_accepted(self) -> None:
        """Even though the catalog knows it. The set of things a company may
        state is narrower than the set of facts that exist, and this is the
        door that keeps it so."""
        self.assertIn("counterparty.country_restricted", asking.catalog())
        self.assertFalse(
            asking.accepts("counterparty.country_restricted", "false")
        )

    def test_the_role_is_read_rather_than_chosen(self) -> None:
        """A fact carried under the wrong evidence role is a fact the rules
        were never meant to accept."""
        self.assertEqual(
            "support_eligibility",
            asking.evidence_role("company.ksure_exporter_grade"),
        )
        self.assertEqual("user_trade", asking.evidence_role("financing.purpose"))
        self.assertEqual(
            "procedure", asking.evidence_role("financing.has_bank_consultation")
        )

    def test_it_is_typed_the_way_the_rules_compare(self) -> None:
        self.assertIs(True, asking.as_stated("financing.has_bank_consultation", "true"))
        self.assertIs(False, asking.as_stated("financing.has_bank_consultation", "false"))
        self.assertEqual("C", asking.as_stated("company.ksure_exporter_grade", "C"))


if __name__ == "__main__":
    unittest.main()
