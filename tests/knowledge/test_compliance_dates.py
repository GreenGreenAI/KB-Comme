import unittest
from datetime import date

from tradeflow.domain.compliance_dates import (
    add_calendar_months,
    deadline_breached,
    mutual_account_entry_deadline,
    mutual_account_settlement_deadline,
)


class MutualAccountDeadlineTests(unittest.TestCase):
    def test_entry_window_uses_exactly_thirty_days(self) -> None:
        basis = date(2026, 7, 1)
        deadline = mutual_account_entry_deadline(basis)
        self.assertEqual(date(2026, 7, 31), deadline)
        self.assertFalse(deadline_breached(deadline, as_of=deadline))
        self.assertTrue(
            deadline_breached(deadline, as_of=date(2026, 8, 1))
        )

    def test_completed_entry_uses_completion_date(self) -> None:
        deadline = date(2026, 7, 31)
        self.assertFalse(
            deadline_breached(
                deadline,
                as_of=date(2026, 8, 10),
                completed_on=date(2026, 7, 31),
            )
        )
        self.assertTrue(
            deadline_breached(
                deadline,
                as_of=date(2026, 8, 10),
                completed_on=date(2026, 8, 1),
            )
        )

    def test_three_month_deadline_uses_calendar_months(self) -> None:
        deadline = mutual_account_settlement_deadline(date(2026, 1, 31))
        self.assertEqual(date(2026, 4, 30), deadline)
        self.assertFalse(deadline_breached(deadline, as_of=deadline))
        self.assertTrue(
            deadline_breached(deadline, as_of=date(2026, 5, 1))
        )
        self.assertEqual(
            date(2024, 2, 29),
            add_calendar_months(date(2023, 11, 30), 3),
        )

    def test_negative_months_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            add_calendar_months(date(2026, 1, 1), -1)

    def test_future_completion_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            deadline_breached(
                date(2026, 7, 31),
                as_of=date(2026, 7, 20),
                completed_on=date(2026, 7, 21),
            )


if __name__ == "__main__":
    unittest.main()
