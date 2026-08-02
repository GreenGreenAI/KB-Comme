import unittest
from datetime import date, timedelta

from fastapi import HTTPException

from tradeflow.web import app
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

    Written against the subjects rather than the sentence: the reading is now
    the keywords plus whatever the model adds, and this holds for both.
    """

    def test_a_filing_question_is_answered_first(self) -> None:
        self.assertTrue(app._leads(("compliance",)))

    def test_a_financing_question_is_answered_first(self) -> None:
        self.assertTrue(app._leads(("support",)))

    def test_an_exposure_question_keeps_the_sentence_first(self) -> None:
        self.assertFalse(app._leads(("market_scenario",)))
        self.assertFalse(app._leads(("exposure",)))
        self.assertFalse(app._leads(("hedge",)))

    def test_a_trade_description_keeps_the_sentence_first(self) -> None:
        """No question in it, so nothing was asked out of order."""
        self.assertFalse(app._leads(()))


class AskingForTests(unittest.TestCase):
    """Which blocked worker gets the top of the screen and an input panel.

    Every skipped worker reports its reason in its own fold, and that does not
    change — but an input panel is a demand, and a demand for a value the
    question did not need reads as the product not having listened. A company
    asking whether its netting is reportable was being asked for its operating
    profit, which is §5.3's input and nobody's answer.
    """

    def _skipped(self, *names: str) -> dict:
        return {"workers": {"skipped": {name: "…" for name in names}}}

    def test_a_filing_question_is_not_asked_for_the_operating_profit(self) -> None:
        self.assertIsNone(app._asking_for(("compliance",), self._skipped("hedge")))

    def test_a_hedge_question_is(self) -> None:
        self.assertEqual(
            "hedge", app._asking_for(("hedge",), self._skipped("hedge"))
        )

    def test_a_trade_description_keeps_the_funnel(self) -> None:
        """§2's reader does not know their exposure well enough to ask about it
        by name, so a sentence that asked about nothing keeps the old
        behaviour."""
        self.assertEqual("hedge", app._asking_for((), self._skipped("hedge")))

    def test_nothing_is_asked_for_when_nothing_is_blocked(self) -> None:
        self.assertIsNone(app._asking_for(("hedge",), {}))


class AnonymousSupportTests(unittest.TestCase):
    """§5.4's rules read company facts and an anonymous caller has none, so a
    question about 지원제도 is answered by naming two facts rather than a
    product. One request, not two: the sentence asks for the facts and stops
    there. Adding 「로그인하시면 계정 사실로 판정합니다」 asked for the same two
    facts a second way, and what the reader had to do went from one to two."""

    def test_it_asks_for_the_two_facts_and_only_that(self) -> None:
        body = analyze_endpoint(
            AnalyzeRequest(
                cases=[],
                utterance="10월 24일 수출 10만 달러인데 받을 수 있는 지원제도가 있나요",
                as_of="2026-07-28",
            )
        )
        pointer = body["result"]["pointer"]

        self.assertIn("기업규모와 신용 상태", pointer)
        self.assertNotIn("로그인", pointer)


class StatedProfileTests(unittest.TestCase):
    """The same two facts by hand, for a company that has not signed up."""

    def _support(self, **body) -> dict:
        return analyze_endpoint(
            AnalyzeRequest(
                cases=[
                    {
                        "direction": "수출",
                        "amount": "100000",
                        "expected_payment_date": "2026-10-24",
                    }
                ],
                utterance="받을 수 있는 지원제도가 있나요",
                as_of="2026-07-28",
                **body,
            )
        )["result"]

    def test_stating_them_produces_a_judgement(self) -> None:
        result = self._support(company_size="small", credit_issue_free=True)

        self.assertNotIn("support", result["workers"]["skipped"])
        self.assertTrue(result["support_candidates"])

    def test_stating_nothing_still_asks(self) -> None:
        """§5.4 must go on reporting the facts as missing rather than being
        handed an invented `False`."""
        result = self._support()

        self.assertIn("support", result["workers"]["skipped"])
        self.assertEqual(
            ["company_size", "credit_issue_free"], result["required_inputs"]["profile"]
        )

    def test_the_size_settles_whether_it_is_an_sme(self) -> None:
        """They are the same claim, and letting them disagree would be a
        contradiction the rules cannot see."""
        result = self._support(company_size="large", credit_issue_free=True)

        self.assertNotIn("support", result["workers"]["skipped"])


class StandingSubjectTests(unittest.TestCase):
    """A request panel sends values and no words.

    Reading intent from that blank reordered the answer back to the default
    the moment the user supplied what was asked for — the judgement they came
    for closed itself as it arrived, and the funnel started asking again.
    """

    def _answer(self, **body) -> dict:
        return analyze_endpoint(
            AnalyzeRequest(
                cases=[
                    {
                        "direction": "수출",
                        "amount": "100000",
                        "expected_payment_date": "2026-10-24",
                    }
                ],
                as_of="2026-07-28",
                company_size="small",
                credit_issue_free=True,
                **body,
            )
        )["result"]

    def test_the_question_still_on_the_table_orders_the_answer(self) -> None:
        result = self._answer(asked_about="받을 수 있는 지원제도가 있나요")

        self.assertEqual("pointer", result["lead"])
        self.assertEqual("support", result["execution_plan"]["section_order"][0])

    def test_a_turn_with_no_subject_at_all_keeps_the_default(self) -> None:
        result = self._answer()

        self.assertEqual("summary", result["lead"])

    def test_the_older_sentence_never_reaches_the_slot_reader(self) -> None:
        """Ordering only. A trade described once must not describe itself a
        second time — two turns would produce two trades."""
        result = self._answer(
            asked_about="12월 3일에 수입대금 5만 달러 지급합니다"
        )

        self.assertEqual(1, len(result["trade_timeline"]))
        self.assertEqual("100000", result["trade_timeline"][0]["amount"])


class AsksMeaningTests(unittest.TestCase):
    """「환변동보험이 뭐야」 and 「받을 수 있는 지원제도가 있나요」 read as the
    same subject and want different things.

    The first has no answer here — the extracts hold eligibility conditions
    and nothing describes what a scheme is for — and the second does. The
    honest line and the request panel both hang on telling them apart.
    """

    TRADE = {
        "direction": "수출",
        "amount": "150000",
        "expected_payment_date": "2026-12-03",
    }

    def _answer(self, utterance: str) -> dict:
        return analyze_endpoint(
            AnalyzeRequest(
                cases=[self.TRADE], utterance=utterance, as_of="2026-07-31"
            )
        )["result"]

    def test_a_question_about_meaning_is_answered_as_one(self) -> None:
        """It lived only on the path taken when there was no trade, so the
        moment a company had described one every question about what something
        is came back as an analysis of that trade."""
        result = self._answer("환변동보험이 뭐야?")

        self.assertIn("설명하는 것은 아직 다루지 않습니다", result["cannot"])

    def test_a_question_about_eligibility_is_not(self) -> None:
        self.assertEqual("", self._answer("받을 수 있는 지원제도가 있나요")["cannot"])

    def test_no_panel_opens_under_a_question_we_declined(self) -> None:
        """A panel is a demand. Opening one under a question we have just said
        we cannot answer asks for facts about something else."""
        self.assertIsNone(self._answer("환변동보험이 뭐야?")["asking_for"])
        self.assertEqual(
            "support", self._answer("받을 수 있는 지원제도가 있나요")["asking_for"]
        )


if __name__ == "__main__":
    unittest.main()


class RetellGuardTests(unittest.TestCase):
    """A rewrite exists to make several judgements read as one answer.

    Given a single line it has nothing to combine and becomes a machine that
    says the same thing twice — and the screen showed both, three lines apart,
    in the same words.
    """

    def _answer(self, **body) -> dict:
        return analyze_endpoint(
            AnalyzeRequest(
                cases=[
                    {
                        "direction": "수출",
                        "amount": "150000",
                        "expected_payment_date": "2026-12-03",
                    }
                ],
                utterance="환율이 더 떨어지면 얼마나 손해인가요",
                as_of="2026-07-31",
                **body,
            )
        )["result"]

    def test_nothing_to_combine_is_not_retold(self) -> None:
        """An anonymous caller gets no eligibility judgement, so the only line
        would be the figures sentence the screen already shows."""
        result = self._answer()

        self.assertEqual([], result["said"]["support"])
        self.assertNotIn("retold", result["said"])

    def test_judgements_are_retold(self) -> None:
        result = self._answer(company_size="small", credit_issue_free=True)

        self.assertTrue(result["said"]["support"])
