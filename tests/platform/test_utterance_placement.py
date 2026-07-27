"""Where a newly heard sentence belongs among the trades already known.

Before this rule every sentence was merged into the latest case, and the merge
kept the existing non-empty values. A company that both exports and imports —
the customer §2.4 names — therefore had its second trade read correctly and
then thrown away: `understood` reported the import, and the answer showed only
the export.
"""

import unittest

from tradeflow.tools.utterance import (
    AMBIGUOUS,
    APPEND,
    MERGE,
    place_utterance,
)

EXPORT = {
    "direction": "export",
    "currency": "USD",
    "amount": "100000",
    "expected_payment_date": "2026-10-24",
    "payment_method": "tt",
}


class PlacementTests(unittest.TestCase):
    def test_the_first_sentence_has_nowhere_else_to_go(self) -> None:
        self.assertEqual(
            MERGE, place_utterance({"direction": "수출"}, []).action
        )

    def test_a_sentence_that_only_fills_blanks_completes_the_trade(self) -> None:
        partial = {"direction": "export", "amount": "100000"}

        placement = place_utterance(
            {"expected_payment_date": "2026-10-24"}, [partial]
        )

        self.assertEqual(MERGE, placement.action)

    def test_restating_the_same_values_is_not_a_new_trade(self) -> None:
        heard = {
            "direction": "수출",
            "amount": "100000",
            "expected_payment_date": "2026-10-24",
        }

        self.assertEqual(MERGE, place_utterance(heard, [EXPORT]).action)

    def test_the_opposite_direction_is_a_different_trade(self) -> None:
        """The defect this rule exists for.

        An export does not become an import while keeping its amount and date,
        so there is nothing to ask about.
        """
        heard = {
            "direction": "수입",
            "amount": "60000",
            "expected_payment_date": "2026-08-25",
        }

        placement = place_utterance(heard, [EXPORT])

        self.assertEqual(APPEND, placement.action)
        self.assertIn("direction", placement.conflicts)

    def test_the_same_direction_with_different_figures_is_asked_about(self) -> None:
        """A second shipment and a correction look identical in the data.

        Guessing append invents a trade the company does not have; guessing
        merge erases one it does. §1.1 says an agent that cannot decide from
        its input stops and asks.
        """
        heard = {
            "direction": "수출",
            "amount": "150000",
            "expected_payment_date": "2026-12-03",
        }

        placement = place_utterance(heard, [EXPORT])

        self.assertEqual(AMBIGUOUS, placement.action)
        self.assertEqual(
            ("amount", "expected_payment_date"), placement.conflicts
        )

    def test_korean_and_english_directions_are_the_same_direction(self) -> None:
        """The extractor says 수출; a case already read by intake says export.

        Comparing them as plain strings would make every second sentence look
        like a direction change, and every one of them would append.
        """
        heard = {"direction": "수출", "amount": "100000"}

        self.assertEqual(MERGE, place_utterance(heard, [EXPORT]).action)

    def test_an_equal_amount_written_differently_is_not_a_conflict(self) -> None:
        heard = {"direction": "수출", "amount": "100000.00"}

        self.assertEqual(MERGE, place_utterance(heard, [EXPORT]).action)

    def test_placement_looks_at_the_latest_trade_only(self) -> None:
        """The sentence continues the conversation, not the whole history."""
        imported = {**EXPORT, "direction": "import", "amount": "60000"}
        heard = {"direction": "수입", "amount": "60000"}

        self.assertEqual(
            MERGE, place_utterance(heard, [EXPORT, imported]).action
        )


if __name__ == "__main__":
    unittest.main()
