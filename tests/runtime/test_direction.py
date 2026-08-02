"""A sentence must not turn the money around.

The figure list says which way it moves — 「그때 덜 받는 원화」 — and §4.2[9]
wrote the opposite anyway: a company with +40,000 USD coming in was told it had
「보내야 할 40,000 USD」 and that a falling rate would cost it 4,108,400 KRW
「더」. Every number was quoted exactly, so `check` and `check_bound` both passed
it. They compare atoms; this is the relation between them.
"""

import unittest

from tradeflow.runtime.synthesis import check, check_bound, check_direction

FIGURES = [
    "거래 순노출: 40,000 USD",
    "그때 덜 받는 원화: 4,108,400 KRW",
]
REVERSED = (
    "보내야 할 40,000 USD가 결제일까지 열려 있습니다. "
    "불리한 쪽인 1,338.39까지 가면 결제에 4,108,400 KRW가 더 듭니다."
)
CORRECT = "받을 40,000 USD가 열려 있고, 그때 4,108,400 KRW를 덜 받습니다."


class DirectionTests(unittest.TestCase):
    def test_the_older_checks_let_it_through(self) -> None:
        """Not a complaint about them — it is why this check exists. Both were
        built to catch invented or re-worn numbers, and every number here is
        quoted exactly and wearing its own unit."""
        self.assertEqual("", check(REVERSED, [*FIGURES, "불리한 쪽 환율: 1,338.39"]))
        self.assertEqual("", check_bound(CORRECT, FIGURES))

    def test_a_receipt_that_became_a_payment_is_refused(self) -> None:
        self.assertIn("방향", check_direction(REVERSED, "decrease"))

    def test_the_right_way_round_passes(self) -> None:
        self.assertEqual("", check_direction(CORRECT, "decrease"))

    def test_an_import_is_checked_the_other_way(self) -> None:
        """Payments rising is the import case, and there 「덜 받」 is the lie."""
        self.assertIn("방향", check_direction(CORRECT, "increase"))
        self.assertEqual("", check_direction(REVERSED, "increase"))

    def test_an_unknown_direction_forbids_nothing(self) -> None:
        """§5.2 reports the direction; when it did not run there is nothing to
        contradict, and refusing every sentence would cost the prose for a
        reason that is not the model's."""
        self.assertEqual("", check_direction(REVERSED, None))


if __name__ == "__main__":
    unittest.main()
