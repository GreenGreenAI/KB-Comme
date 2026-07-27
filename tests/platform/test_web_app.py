import unittest
from datetime import date, timedelta

from fastapi import HTTPException

from tradeflow.web.app import AnalyzeRequest, analyze_endpoint


class WebApiValidationTests(unittest.TestCase):
    def test_a_company_profile_puts_the_support_worker_back_in(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                is_sme=True,
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

        self.assertIn("support", body["result"]["execution_plan"]["planned"])
        self.assertTrue(body["result"]["packet_id"].startswith("decision:"))

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

        # §4.2[2]: with no company profile and no declared trade structure,
        # neither knowledge worker is in the plan — and each says what would
        # put it there rather than leaving its section blank.
        plan = body["result"]["execution_plan"]
        self.assertEqual(["exposure", "market_scenario"], plan["planned"])
        skipped = body["result"]["workers"]["skipped"]
        self.assertIn("기업규모", skipped["support"])
        self.assertIn("신고 불필요로 판단하지 않습니다", skipped["compliance"])

        # Fail-closed, and the reason reaches the caller. Which reason applies
        # depends on how old the committed snapshot is on the day this runs, so
        # the specific wording is asserted in test_orchestrator.py, which builds
        # its own snapshot instead of reading the repository's.
        self.assertIsNone(body["result"]["hedge_analysis"])
        self.assertIn("hedge", body["result"]["workers"]["skipped"])


class SecondTradeTests(unittest.TestCase):
    """A sentence about a different trade must reach the answer.

    Merging it into the latest case discarded it silently: the response said
    it had been understood and then showed figures that ignored it.
    """

    def _export(self) -> dict:
        return {
            "direction": "export",
            "currency": "USD",
            "amount": "100000",
            "expected_payment_date": (
                date.today() + timedelta(days=90)
            ).isoformat(),
            "payment_method": "tt",
        }

    def test_an_import_sentence_adds_a_trade_instead_of_vanishing(self) -> None:
        due = date.today() + timedelta(days=30)
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=(
                    f"{due.month}월 {due.day}일에 수입대금 6만 달러도 나가요"
                ),
            )
        )

        timeline = body["result"]["trade_timeline"]
        self.assertEqual(2, len(timeline))
        self.assertEqual(
            ["export", "import"], [case["direction"] for case in timeline]
        )

    def test_the_added_trade_changes_the_figures_it_should(self) -> None:
        """Proof the case reached the calculation, not just the echo."""
        due = date.today() + timedelta(days=30)
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=(
                    f"{due.month}월 {due.day}일에 수입대금 6만 달러도 나가요"
                ),
            )
        )

        cash = body["result"]["cashflow_analysis"]
        self.assertEqual("40000", cash["net_exposure"][0]["amount"])
        self.assertEqual("60000", cash["natural_hedge_amount"][0]["amount"])

    def test_an_ambiguous_sentence_is_asked_about_not_guessed(self) -> None:
        due = date.today() + timedelta(days=150)
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=(
                    f"{due.month}월 {due.day}일에 수출대금 15만 달러 받아요"
                ),
            )
        )

        self.assertEqual("needs_placement", body["status"])
        self.assertEqual(
            ["append", "merge"],
            [option["placement"] for option in body["options"]],
        )
        self.assertNotIn("result", body)

    def test_the_users_answer_is_obeyed_without_asking_again(self) -> None:
        due = date.today() + timedelta(days=150)
        utterance = f"{due.month}월 {due.day}일에 수출대금 15만 달러 받아요"

        added = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=utterance,
                placement="append",
            )
        )
        corrected = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=utterance,
                placement="merge",
            )
        )

        self.assertEqual(2, len(added["result"]["trade_timeline"]))
        self.assertEqual(1, len(corrected["result"]["trade_timeline"]))


if __name__ == "__main__":
    unittest.main()
