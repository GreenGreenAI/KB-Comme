import unittest
from datetime import date

from tradeflow.knowledge.mutual_account import (
    MutualAccountTimeline,
    derive_mutual_account_timeline,
)


class MutualAccountTimelineTests(unittest.TestCase):
    def test_deadlines_are_derived_as_evidence_bound_facts(self) -> None:
        result = derive_mutual_account_timeline(
            case_id="CASE-1",
            timeline=MutualAccountTimeline(
                entry_basis_date=date(2026, 6, 1),
                entry_completed_on=date(2026, 7, 1),
                period_end=date(2026, 3, 31),
                balance_filing_completed_on=date(2026, 6, 30),
            ),
            as_of=date(2026, 7, 27),
        )

        self.assertEqual(date(2026, 7, 1), result.deadlines["entry"])
        self.assertEqual(
            date(2026, 6, 30),
            result.deadlines["balance_filing"],
        )
        facts = result.evidence.payload["facts"]
        self.assertFalse(
            facts["payment.mutual_account.entry_deadline_breached"]
        )
        self.assertFalse(
            facts[
                "payment.mutual_account.balance_filing_deadline_breached"
            ]
        )
        self.assertTrue(
            facts[
                "payment.mutual_account.balance_settlement_deadline_breached"
            ]
        )
        self.assertEqual(
            {"CASE-1", "mutual-account-deadlines"},
            set(result.evidence.identifiers),
        )

    def test_day_after_deadline_is_a_breach(self) -> None:
        result = derive_mutual_account_timeline(
            case_id="CASE-1",
            timeline=MutualAccountTimeline(
                period_end=date(2026, 1, 31),
                balance_filing_completed_on=date(2026, 5, 1),
            ),
            as_of=date(2026, 5, 1),
        )

        self.assertTrue(
            result.evidence.payload["facts"][
                "payment.mutual_account.balance_filing_deadline_breached"
            ]
        )

    def test_future_completion_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "after as_of"):
            derive_mutual_account_timeline(
                case_id="CASE-1",
                timeline=MutualAccountTimeline(
                    entry_basis_date=date(2026, 6, 1),
                    entry_completed_on=date(2026, 8, 1),
                ),
                as_of=date(2026, 7, 27),
            )


if __name__ == "__main__":
    unittest.main()
