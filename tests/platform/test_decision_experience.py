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

    def test_question_blocking_more_decisions_is_ranked_first(self) -> None:
        result = _result(gap="0", consulted_status="insufficient_information")
        result["missing_input_queue"] = [
            {
                "field": "financing.has_bank_consultation",
                "scope": "case",
                "subject_id": "EXPORT-002",
            },
            {
                "field": "company.size",
                "scope": "profile",
                "subject_id": "EXPORT-002",
            },
        ]
        result["support_candidates"] = [
            {
                "subject_id": "EXPORT-002",
                "rule_id": "RULE-1",
                "missing_fields": ["company.size"],
            },
            {
                "subject_id": "EXPORT-002",
                "rule_id": "RULE-2",
                "missing_fields": ["company.size"],
            },
            {
                "subject_id": "EXPORT-002",
                "rule_id": "RULE-3",
                "missing_fields": ["financing.has_bank_consultation"],
            },
        ]

        questions = build_next_decisive_questions(result, opening_balances={})

        self.assertEqual("company.size", questions[0]["field"])
        self.assertEqual(2, questions[0]["affected_decision_count"])
        self.assertEqual(1, questions[1]["affected_decision_count"])


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

    def test_preserves_actual_status_when_candidate_moves_to_excluded(self) -> None:
        before = _result(gap="0", consulted_status="conditionally_eligible")
        after = _result(gap="0", consulted_status="conditionally_eligible")
        excluded = after["support_candidates"].pop()
        excluded["status"] = "not_eligible"
        excluded["matched"] = False
        after["excluded_candidates"] = [excluded]

        delta = compare_decisions(
            before,
            after,
            previous_analysis_run_id="RUN-BEFORE",
        )

        candidate = next(
            item
            for item in delta["changes"]
            if item["metric"] == "support_candidate_status"
        )
        self.assertEqual("conditionally_eligible", candidate["before"])
        self.assertEqual("not_eligible", candidate["after"])

    def test_reports_added_actions_and_changed_document_checklists(self) -> None:
        before = _result(gap="0", consulted_status="conditionally_eligible")
        after = _result(gap="0", consulted_status="conditionally_eligible")
        before["next_actions"] = [{
            "subject_id": "EXPORT-002",
            "action": "consult_and_apply_for_ksure_product",
            "authority": "ksure",
            "required_documents": ["신청서"],
            "source_ids": ["SOURCE-1"],
        }]
        after["next_actions"] = [
            {
                **before["next_actions"][0],
                "required_documents": ["신청서", "수출계약서"],
            },
            {
                "subject_id": "EXPORT-002",
                "action": "file_report",
                "authority": "bok",
                "required_documents": ["신고서"],
                "source_ids": ["SOURCE-2"],
            },
        ]

        delta = compare_decisions(
            before,
            after,
            previous_analysis_run_id="RUN-BEFORE",
        )

        self.assertIn(
            ("next_action", "not_required", "required"),
            {
                (item["metric"], item["before"], item["after"])
                for item in delta["changes"]
                if item["kind"] == "decision_action"
            },
        )
        documents = next(
            item
            for item in delta["changes"]
            if item["kind"] == "required_documents"
        )
        self.assertEqual(["신청서"], documents["before"])
        self.assertEqual(["수출계약서", "신청서"], documents["after"])


if __name__ == "__main__":
    unittest.main()
