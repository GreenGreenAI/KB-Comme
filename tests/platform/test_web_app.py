import unittest
from datetime import date, timedelta

from fastapi import HTTPException

from tradeflow.web.app import AnalyzeRequest, analyze_endpoint


class WebApiValidationTests(unittest.TestCase):
    def test_invalid_money_is_rejected_instead_of_treated_as_missing(self) -> None:
        with self.assertRaises(HTTPException) as context:
            analyze_endpoint(AnalyzeRequest(baseline_profit="not-a-number"))

        self.assertEqual(422, context.exception.status_code)
        self.assertEqual("baseline_profit", context.exception.detail["field"])

    def test_invalid_and_future_analysis_dates_are_rejected(self) -> None:
        with self.assertRaises(HTTPException) as invalid:
            analyze_endpoint(AnalyzeRequest(as_of="2026-99-99"))
        with self.assertRaises(HTTPException) as future:
            analyze_endpoint(
                AnalyzeRequest(
                    as_of=(date.today() + timedelta(days=1)).isoformat()
                )
            )

        self.assertEqual(422, invalid.exception.status_code)
        self.assertEqual(422, future.exception.status_code)

    def test_ready_response_is_bound_to_role_a_decision_packet(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[
                    {
                        "direction": "export",
                        "currency": "USD",
                        "amount": "100000",
                        "expected_payment_date": (
                            date.today() + timedelta(days=30)
                        ).isoformat(),
                    },
                ],
            )
        )

        self.assertEqual("ready", body["status"])
        self.assertTrue(body["result"]["packet_id"].startswith("decision:"))
        self.assertIn("support", body["result"]["workers"]["completed"])
        self.assertIn("compliance", body["result"]["workers"]["completed"])

        # Fail-closed, and the reason reaches the caller. Which reason applies
        # depends on how old the committed snapshot is on the day this runs, so
        # the specific wording is asserted in test_orchestrator.py, which builds
        # its own snapshot instead of reading the repository's.
        self.assertIsNone(body["result"]["hedge_analysis"])
        self.assertIn("hedge", body["result"]["workers"]["skipped"])


if __name__ == "__main__":
    unittest.main()
