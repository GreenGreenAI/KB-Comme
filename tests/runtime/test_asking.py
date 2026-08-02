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

    def test_it_asks_only_for_what_the_company_is_the_one_to_know(self) -> None:
        """A rule reports every fact it is short of. Two kinds must not be put
        to the reader: one we look up, and one we already have.

        Asking a company whether its buyer's country is on K-SURE's restricted
        list is asking them to make our judgement, and their answer would be
        evidence of nothing."""
        result = {
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

        asked = [item["field"] for item in asking.questions(result)]

        self.assertEqual(["company.ksure_exporter_grade"], asked)

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
