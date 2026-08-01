import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from tradeflow.runtime.accounts import AccountStore
from tradeflow.web import app
from tradeflow.web.app import (
    AnalyzeRequest,
    ConsultationHandoffRequest,
    ProfileFactsRequest,
    analysis_history,
    analyze_endpoint,
    create_consultation_handoff,
    saved_analysis,
    update_profile,
)


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


class AskedPairingTests(unittest.TestCase):
    """The field asked for and the question quoted must be the same thing.

    `missing` is in schema order while asking follows ASK_ORDER, so a screen
    reading `missing[0]` for the field and `questions[0]` for the wording put a
    direction chooser under a question about the payment date.
    """

    def _asked(self, case: dict) -> list[dict]:
        body = analyze_endpoint(
            AnalyzeRequest(as_of=date.today().isoformat(), cases=[case])
        )
        self.assertEqual("needs_input", body["status"])
        return body["asked"]

    def test_the_first_asked_field_matches_the_first_question(self) -> None:
        asked = self._asked({"amount": "100000"})

        self.assertEqual("expected_payment_date", asked[0]["field"])
        self.assertIn("날짜", asked[0]["question"])

    def test_pairing_holds_when_a_different_slot_is_missing(self) -> None:
        asked = self._asked({"direction": "export"})

        self.assertEqual("amount", asked[0]["field"])
        self.assertIn("금액", asked[0]["question"])

    def test_asked_agrees_with_the_questions_it_renders(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(as_of=date.today().isoformat(), cases=[{}])
        )

        self.assertEqual(
            body["questions"], [item["question"] for item in body["asked"]]
        )

    def test_every_asked_field_is_actually_missing(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(as_of=date.today().isoformat(), cases=[{}])
        )

        for item in body["asked"]:
            self.assertIn(item["field"], body["missing"])


class MultipleTradeIntakeTests(unittest.TestCase):
    def test_mixed_trade_sentence_never_returns_partial_normal_result(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                utterance=(
                    "베트남에서 원자재 6만 달러를 수입해 8월 25일에 지급하고, "
                    "완제품을 미국에 10만 달러 수출해 10월 24일에 받습니다."
                ),
            )
        )

        self.assertEqual("needs_trade_split", body["status"])
        self.assertNotIn("result", body)
        self.assertEqual(2, len(body["candidates"]))
        self.assertEqual("수입", body["candidates"][0]["direction"])
        self.assertEqual("60000", body["candidates"][0]["amount"])
        self.assertEqual("수출", body["candidates"][1]["direction"])
        self.assertEqual("100000", body["candidates"][1]["amount"])

    def test_support_question_does_not_create_a_phantom_export_trade(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                utterance=(
                    "베트남에서 원자재 6만 달러를 수입해 8월 25일에 지급하고, "
                    "완제품을 미국에 10만 달러 수출해 10월 24일에 받습니다. "
                    "그 사이 부족한 자금과 환위험, 받을 수 있는 수출지원이 궁금합니다."
                ),
            )
        )

        self.assertEqual("needs_trade_split", body["status"])
        self.assertEqual(2, len(body["candidates"]))
        self.assertEqual(
            ["수입", "수출"],
            [item["direction"] for item in body["candidates"]],
        )

    def test_confirmed_split_cases_produce_the_expected_maturity_gap(self) -> None:
        as_of = date.today()
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=as_of.isoformat(),
                opening_balance_usd="0",
                cases=[
                    {
                        "direction": "import",
                        "amount": "60000",
                        "currency": "USD",
                        "payment_method": "TT",
                        "expected_payment_date": (
                            as_of + timedelta(days=30)
                        ).isoformat(),
                    },
                    {
                        "direction": "export",
                        "amount": "100000",
                        "currency": "USD",
                        "payment_method": "TT",
                        "expected_payment_date": (
                            as_of + timedelta(days=90)
                        ).isoformat(),
                    },
                ],
            )
        )

        self.assertEqual("ready", body["status"])
        exposure = body["result"]["cashflow_analysis"]
        self.assertEqual("60000", exposure["funding_gap"][0]["peak_amount"])
        self.assertEqual(
            "40000",
            exposure["net_exposure"][0]["amount"],
        )
        self.assertTrue(body["result"]["summary"])
        self.assertIn("60,000 USD", body["result"]["summary"])


class ProfilePolicyWebIntegrationTests(unittest.TestCase):
    def test_ready_response_exposes_profile_policy_and_capability_trace(self) -> None:
        as_of = date.today()
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=as_of.isoformat(),
                company_name="한빛정밀",
                is_sme=True,
                company_facts={"company.size": "small"},
                cases=[{
                    "direction": "export",
                    "amount": "100000",
                    "currency": "USD",
                    "payment_method": "TT",
                    "expected_payment_date": (
                        as_of + timedelta(days=60)
                    ).isoformat(),
                    "country": "US",
                }],
            )
        )

        self.assertEqual("ready", body["status"])
        result = body["result"]
        self.assertEqual("1.0", result["profile_policy"]["schema_version"])
        self.assertIn(
            "exporter",
            result["profile_policy"]["axes"]["trade_role"],
        )
        self.assertIsInstance(result["capability_trace"], list)

    def test_missing_work_is_partitioned_by_actor(self) -> None:
        as_of = date.today()
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=as_of.isoformat(),
                is_sme=True,
                company_facts={
                    "company.is_domestic": True,
                    "company.size": "small",
                    "company.credit_issue_free": True,
                    "company.ksure_exporter_grade": "A",
                },
                cases=[{
                    "direction": "export",
                    "amount": "100000",
                    "currency": "USD",
                    "payment_method": "TT",
                    "expected_payment_date": (
                        as_of + timedelta(days=60)
                    ).isoformat(),
                    "country": "US",
                    "case_facts": {"trade.payment_term_days": 60},
                }],
            )
        )

        result = body["result"]
        question_ids = {
            item["question_id"] for item in result["user_questions"]
        }
        self.assertIn("trade_structure_confirmation", question_ids)
        capabilities = {
            item["capability_id"] for item in result["system_fetches"]
        }
        self.assertIn("ksure.country_policy.lookup.v1", capabilities)
        self.assertIn("ksure.importer_grade.lookup.v1", capabilities)
        self.assertTrue(result["expert_tasks"])

    def test_failed_market_worker_becomes_a_system_refresh_task(self) -> None:
        from tradeflow.web.app import _add_runtime_fetches

        result = {
            "workers": {
                "completed": ["exposure"],
                "failed": {"market_scenario": "snapshot is stale"},
                "skipped": {},
            },
            "system_fetches": [],
        }

        _add_runtime_fetches(result)

        self.assertEqual(
            "market_data.ecos_usd_krw.refresh.v1",
            result["system_fetches"][0]["capability_id"],
        )
        self.assertEqual(
            "provider_unavailable",
            result["system_fetches"][0]["status"],
        )


class DecisionWorkspaceContractTests(unittest.TestCase):
    def _case(self, **changes) -> dict:
        return {
            "direction": "export",
            "currency": "USD",
            "amount": "100000",
            "expected_payment_date": (
                date.today() + timedelta(days=60)
            ).isoformat(),
            **changes,
        }

    def test_anonymous_company_facts_reach_the_packet_and_profile_projection(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                company_name="한빛정밀",
                is_sme=True,
                company_facts={
                    "company.is_domestic": True,
                    "company.size": "small",
                    "company.credit_issue_free": True,
                    "company.ksure_exporter_grade": "A",
                },
                cases=[self._case()],
            )
        )

        profile = body["result"]["company_profile"]
        self.assertEqual("한빛정밀", profile["company_name"])
        self.assertEqual("small", profile["facts"]["company.size"])
        packet_inputs = dict(
            (item["name"], item["value"])
            for item in body["result"]["decision_packet"]["inputs"]
        )
        self.assertEqual(
            "small", packet_inputs["cases"]["EXPORT-001"]["company.size"]
        )

    def test_case_financing_answers_are_evidenced_and_reused_for_redecision(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                is_sme=True,
                company_facts={"company.size": "small"},
                cases=[
                    self._case(
                        case_facts={
                            "trade.payment_term_days": 180,
                            "financing.purpose": "trade_finance",
                            "financing.has_bank_consultation": True,
                        }
                    )
                ],
            )
        )

        self.assertEqual("ready", body["status"])
        packet_inputs = {
            item["name"]: item["value"]
            for item in body["result"]["decision_packet"]["inputs"]
        }
        facts = packet_inputs["cases"]["EXPORT-001"]
        self.assertEqual(180, facts["trade.payment_term_days"])
        self.assertEqual("trade_finance", facts["financing.purpose"])
        self.assertIs(True, facts["financing.has_bank_consultation"])
        missing = {
            item["field"] for item in body["result"]["missing_input_queue"]
        }
        self.assertNotIn("trade.payment_term_days", missing)
        self.assertNotIn("financing.purpose", missing)
        self.assertNotIn("financing.has_bank_consultation", missing)

    def test_invalid_case_financing_answers_are_rejected(self) -> None:
        with self.assertRaises(HTTPException) as context:
            analyze_endpoint(
                AnalyzeRequest(
                    as_of=date.today().isoformat(),
                    cases=[
                        self._case(
                            case_facts={
                                "financing.has_bank_consultation": "yes"
                            }
                        )
                    ],
                )
            )

        self.assertEqual(422, context.exception.status_code)

    def test_confirmed_gateway_declaration_runs_compliance_with_evidence(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                is_sme=True,
                cases=[self._case()],
                compliance_declarations=[
                    {
                        "case_index": 0,
                        "confirmed": True,
                        "is_netting": False,
                        "is_third_party": False,
                        "uses_mutual_account": False,
                        "uses_foreign_exchange_bank": True,
                    }
                ],
            )
        )

        result = body["result"]
        self.assertIn("compliance", result["workers"]["completed"])
        evidence = result["decision_packet"]["evidence"]
        declaration = next(
            item for item in evidence
            if item["evidence_id"] == "declaration:WEB-EXPORT-001"
        )
        self.assertEqual(
            True,
            declaration["payload"]["facts"][
                "payment.uses_foreign_exchange_bank"
            ],
        )

    def test_unknown_profile_and_case_facts_are_rejected(self) -> None:
        with self.assertRaises(HTTPException) as profile_error:
            analyze_endpoint(
                AnalyzeRequest(
                    cases=[self._case()],
                    company_facts={"company.untrusted_override": True},
                )
            )
        with self.assertRaises(HTTPException) as case_error:
            analyze_endpoint(
                AnalyzeRequest(
                    cases=[
                        self._case(
                            case_facts={"payment.filing_completed": True}
                        )
                    ],
                )
            )

        self.assertEqual(422, profile_error.exception.status_code)
        self.assertEqual(422, case_error.exception.status_code)

    def test_response_exposes_prioritized_inputs_and_official_source_metadata(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                is_sme=True,
                cases=[self._case()],
            )
        )
        result = body["result"]

        self.assertEqual(
            "profile", result["missing_input_queue"][0]["scope"]
        )
        official = [
            item for item in result["evidence"]
            if item["role"] == "official_source"
        ]
        self.assertTrue(official)
        self.assertTrue(any(item.get("url") for item in official))

    def test_signed_in_analysis_is_saved_and_profile_updates_are_persistent(self) -> None:
        with TemporaryDirectory() as directory:
            store = AccountStore(Path(directory) / "accounts.db")
            account = store.create(
                "owner@example.com",
                "pw",
                company_name="한빛정밀",
                account_id="COMPANY-HANBIT",
            )
            token = store.open_session(account)
            with patch("tradeflow.web.app.accounts", store):
                updated = update_profile(
                    ProfileFactsRequest(
                        facts={"company.size": "small"}
                    ),
                    token,
                )
                body = analyze_endpoint(
                    AnalyzeRequest(
                        as_of=date.today().isoformat(),
                        cases=[self._case()],
                    ),
                    token,
                )
                history = analysis_history(token)["analyses"]
                stored = saved_analysis(body["analysis_run_id"], token)
                handoff = create_consultation_handoff(
                    body["analysis_run_id"],
                    ConsultationHandoffRequest(consent=True),
                    token,
                )["handoff"]
                audit = store.list_audit(account)

        self.assertEqual("small", updated["account"]["facts"]["company.size"])
        self.assertEqual(1, len(history))
        self.assertEqual(body["result"]["packet_id"], stored["packet_id"])
        self.assertEqual(
            "KB_KOOKMIN_BANK",
            handoff["channel"]["target_bank"],
        )
        self.assertEqual(
            "ready_for_manual_handoff",
            handoff["state"],
        )
        self.assertFalse(handoff["privacy"]["raw_document_content_included"])
        self.assertFalse(handoff["privacy"]["transmission_performed"])
        self.assertTrue(
            any(
                item["action"] == "consultation_handoff.prepare"
                for item in audit
            )
        )


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
        self.assertEqual(
            "150000",
            corrected["result"]["trade_timeline"][0]["amount"],
        )

    def test_direction_correction_is_confirmed_then_updates_the_trade(
        self,
    ) -> None:
        utterance = "이 거래 방향은 수입으로 정정해 주세요"
        question = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=utterance,
            )
        )

        self.assertEqual("needs_placement", question["status"])

        corrected = analyze_endpoint(
            AnalyzeRequest(
                as_of=date.today().isoformat(),
                cases=[self._export()],
                utterance=utterance,
                placement="merge",
            )
        )

        timeline = corrected["result"]["trade_timeline"]
        self.assertEqual(1, len(timeline))
        self.assertEqual("import", timeline[0]["direction"])


class AnswerOrderTests(unittest.TestCase):
    """Which of the two things the reader meets first.

    §4.2[9]'s sentence may only quote `figures()`, and every figure in it is an
    exposure, a rate or a hedge ratio. That division is the safety of the whole
    design and it stays — but it meant a company asking about 제작 자금 always
    opened the answer on its exchange-rate exposure, with the judgement it had
    asked for two lines below in the code-owned pointer.
    """

    def test_a_financing_question_is_answered_first(self) -> None:
        self.assertTrue(
            app._pointer_leads(
                "제품 제작에 들어갈 자금이 부족합니다. 무역금융이 있을까요?"
            )
        )

    def test_a_filing_question_is_answered_first(self) -> None:
        self.assertTrue(app._pointer_leads("신고해야 할 게 있나요?"))

    def test_an_exposure_question_keeps_the_sentence_first(self) -> None:
        self.assertFalse(app._pointer_leads("환율이 얼마나 오를까요?"))

    def test_a_trade_description_keeps_the_sentence_first(self) -> None:
        """No question in it, so nothing was asked out of order."""
        self.assertFalse(
            app._pointer_leads("10월 24일에 수출대금 10만 달러 받기로 했어요")
        )
        self.assertFalse(app._pointer_leads(None))


if __name__ == "__main__":
    unittest.main()
