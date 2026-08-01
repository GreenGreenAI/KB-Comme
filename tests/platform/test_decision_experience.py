from __future__ import annotations

import unittest

from tradeflow.contracts.decision_experience import (
    build_next_decisive_questions,
    compare_decisions,
)


def _result(*, gap: str, consulted_status: str) -> dict:
    return {
        "packet_id": f"decision:{gap}:{consulted_status}",
        "cashflow_analysis": {
            "funding_gap": [{"currency": "USD", "peak_amount": gap}],
            "net_exposure": [{"currency": "USD", "amount": "40000"}],
            "natural_hedge_amount": [{"currency": "USD", "amount": "60000"}],
            "maturity_matched_amount": [{"currency": "USD", "amount": "0"}],
        },
        "support_candidates": [{
            "subject_id": "EXPORT-002",
            "rule_id": "KSURE_EXPORT_CREDIT_GUARANTEE_PRESHIPMENT_CANDIDATE",
            "title": "K-SURE 수출신용보증(선적전) 후보",
            "status": consulted_status,
            "source_ids": ["KSURE_EXPORT_CREDIT_GUARANTEE_PRESHIPMENT"],
        }],
        "missing_input_queue": [{
            "field": "financing.has_bank_consultation",
            "scope": "case",
            "subject_id": "EXPORT-002",
            "reason": "K-SURE 수출신용보증(선적전) 후보",
        }],
    }


class NextDecisiveQuestionTests(unittest.TestCase):
    def test_funding_gap_balance_is_ranked_before_rule_inputs(self) -> None:
        result = _result(gap="60000", consulted_status="insufficient_information")

        questions = build_next_decisive_questions(result, opening_balances={})

        self.assertEqual("opening_balance_usd", questions[0]["field"])
        self.assertEqual(["최대 자금 공백"], questions[0]["changes"])
        self.assertEqual("60000", questions[0]["impact_preview"]["current"])
        self.assertEqual(
            "financing.has_bank_consultation",
            questions[1]["field"],
        )

    def test_recorded_balance_removes_the_balance_question(self) -> None:
        result = _result(gap="40000", consulted_status="insufficient_information")

        questions = build_next_decisive_questions(
            result,
            opening_balances={"USD": "20000"},
        )

        self.assertNotIn("opening_balance_usd", {item["field"] for item in questions})


class DecisionDeltaTests(unittest.TestCase):
    def test_reports_cashflow_candidate_and_resolved_question_changes(self) -> None:
        before = _result(gap="60000", consulted_status="insufficient_information")
        before["next_decisive_questions"] = build_next_decisive_questions(
            before,
            opening_balances={},
        )
        after = _result(gap="40000", consulted_status="expert_confirmation_required")
        after["missing_input_queue"] = []
        after["next_decisive_questions"] = build_next_decisive_questions(
            after,
            opening_balances={"USD": "20000"},
        )

        delta = compare_decisions(
            before,
            after,
            previous_analysis_run_id="RUN-BEFORE",
        )

        self.assertTrue(delta["changed"])
        self.assertEqual("RUN-BEFORE", delta["previous_analysis_run_id"])
        self.assertIn(
            ("funding_gap", "60000", "40000"),
            {
                (item["metric"], item["before"], item["after"])
                for item in delta["changes"]
            },
        )
        self.assertIn(
            (
                "support_candidate_status",
                "insufficient_information",
                "expert_confirmation_required",
            ),
            {
                (item["metric"], item["before"], item["after"])
                for item in delta["changes"]
            },
        )
        self.assertEqual(
            {"opening_balance_usd", "financing.has_bank_consultation"},
            {item["field"] for item in delta["resolved_questions"]},
        )


if __name__ == "__main__":
    unittest.main()
