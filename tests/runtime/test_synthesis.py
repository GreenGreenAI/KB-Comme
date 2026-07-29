import json
import unittest
from types import SimpleNamespace

from tradeflow.runtime.synthesis import (
    Synthesizer,
    check,
    digit_runs,
    TIMEOUT_S,
    figures,
    pointer,
    redact,
    verdicts,
)

FIGURES = [
    "순노출: 100,000 USD",
    "불리한 쪽 환율: 1361.05 (KRW per USD, 신뢰수준 0.9)",
    "그때 원화 수취액 차이: 10,525,000 KRW (감소)",
    "관측 조건: 최근 60영업일, 잔여 63영업일, 드리프트 0 고정",
]


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def create(self, **request):
        self.request = request
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload, ensure_ascii=False)
                    )
                )
            ]
        )


def synthesizer_returning(payload):
    synthesizer = Synthesizer(api_key="test")
    completions = FakeCompletions(payload)
    synthesizer._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return synthesizer, completions


class DigitRunTests(unittest.TestCase):
    def test_a_number_is_read_as_it_was_written(self) -> None:
        self.assertEqual(digit_runs("1,361.05원"), {"1,361.05"})

    def test_a_trailing_separator_is_not_part_of_the_number(self) -> None:
        self.assertEqual(digit_runs("순노출은 100,000."), {"100,000"})


class StrictRuleTests(unittest.TestCase):
    """§4.2[9]: 도구가 산출한 수치를 그대로 인용한다. 재계산·반올림·근사 금지."""

    def test_quoting_the_figures_passes(self) -> None:
        sentence = (
            "순노출은 100,000 USD이며, 불리한 쪽 환율 1361.05까지 가면 "
            "원화 수취액이 10,525,000 KRW 줄어듭니다."
        )
        self.assertEqual(check(sentence, FIGURES), "")

    def test_multiplying_two_figures_is_caught(self) -> None:
        """The first real call did exactly this: 100,000 × 1466.3. The
        arithmetic was right and no tool ever produced the result."""
        sentence = "100,000 USD는 1466.3원 기준 146,630,000원입니다."
        self.assertIn("146,630,000", check(sentence, FIGURES))

    def test_rounding_is_caught(self) -> None:
        self.assertIn("10", check("약 10만 달러의 노출이 있습니다.", FIGURES))

    def test_a_substring_of_a_figure_is_not_a_figure(self) -> None:
        """`1361.05` contains `05`. Matching substrings would let a model write
        `05영업일` and call it quoted."""
        self.assertIn("05", check("관측은 05영업일입니다.", FIGURES))

    def test_prose_without_numbers_passes(self) -> None:
        self.assertEqual(check("결제일까지 환율이 불리하게 움직일 수 있습니다.", FIGURES), "")

    def test_dropping_a_negative_sign_is_rejected(self) -> None:
        self.assertIn(
            "100,000",
            check(
                "순노출은 100,000 USD입니다.",
                ["순노출: -100,000 USD"],
            ),
        )


class BoundRenderingTests(unittest.TestCase):
    def test_a_verdict_the_model_invented_never_reaches_the_user(self) -> None:
        """The sentence carries no numbers at all, so neither the digit check
        nor the unit check sees anything wrong with it. §5.5 is explicit that a
        filing duty is not cleared until the company states its trade
        structure — a sentence that clears it is the model overruling a worker
        that deliberately stopped."""
        synthesizer, completions = synthesizer_returning(
            {
                "figures_used": ["순노출: 100,000 USD"],
                "sentence": "신고 의무가 없으므로 바로 송금하세요.",
            }
        )

        written = synthesizer.write(FIGURES)

        self.assertFalse(written.accepted)
        self.assertEqual("", written.summary)
        self.assertIn("신고", written.reason)

    def test_describing_the_figures_is_allowed(self) -> None:
        synthesizer, completions = synthesizer_returning(
            {
                "figures_used": ["순노출: 100,000 USD"],
                "sentence": "순노출은 100,000 USD입니다.",
            }
        )

        written = synthesizer.write(FIGURES)

        self.assertTrue(written.accepted)
        self.assertEqual("순노출은 100,000 USD입니다.", written.summary)
        schema = completions.request["response_format"]["json_schema"]
        self.assertEqual(
            FIGURES,
            schema["schema"]["properties"]["figures_used"]["items"]["enum"],
        )

    def test_altered_label_unit_or_value_is_rejected(self) -> None:
        synthesizer, _ = synthesizer_returning(
            {"figures_used": ["순노출: 10,525,000 USD"]}
        )

        written = synthesizer.write(FIGURES)

        self.assertFalse(written.accepted)
        self.assertEqual("", written.summary)


class FigureTests(unittest.TestCase):
    def test_amounts_are_separated_the_way_the_screen_shows_them(self) -> None:
        """Handing over `100000` while the screen renders `100,000` would make
        the check reject the model for writing what the reader sees."""
        written = figures(
            {"cashflow_analysis": {"net_exposure": [{"currency": "USD", "amount": "100000"}]}}
        )
        self.assertEqual(written, ["순노출: 100,000 USD"])

    def test_a_rate_carries_its_unit_and_its_reference_moment(self) -> None:
        """§4.2[9]: 수치의 단위·기준환율·기준시점을 함께 표기한다."""
        written = figures(
            {
                "market_scenario": {
                    "spot_rate": "1466.3",
                    "adverse_rate": "1361.05",
                    "adverse_cashflow_amount": "10525000",
                    "adverse_cashflow_direction": "decrease",
                    "unit": "KRW per USD",
                    "observed_to": "2026-07-27",
                    "confidence_level": 0.9,
                    "observation_days": 60,
                    "horizon_business_days": 63,
                    "drift": "0 고정",
                }
            }
        )
        joined = " ".join(written)
        self.assertIn("KRW per USD", joined)
        self.assertIn("2026-07-27", joined)
        self.assertIn("10,525,000", joined)

    def test_an_empty_result_offers_nothing_to_quote(self) -> None:
        self.assertEqual(figures({}), [])


class PromptHygieneTests(unittest.TestCase):
    """Two failures the live model produced, fixed and pinned."""

    def test_an_instruction_is_caught_whatever_ending_it_wears(self) -> None:
        """`검토해 보세요` passed a list that had `하세요` and not `보세요`."""
        for sentence in (
            "무역금융 활용 가능성을 검토해 보세요.",
            "지금 환전하십시오.",
            "선물환을 권해 드립니다.",
        ):
            with self.subTest(sentence=sentence):
                self.assertTrue(verdicts(sentence))

    def test_the_redaction_marker_never_reaches_the_reader(self) -> None:
        """The question's numbers are elided before the answer path sees them,
        and the model copied the marker straight through: `○○억 원 규모 장비`.
        It is an editing device for the prompt, not Korean."""
        synthesizer, _ = synthesizer_returning(
            {
                "figures_used": ["순노출: 100,000 USD"],
                "sentence": "○○억 원 규모 수출의 순노출은 100,000 USD입니다.",
            }
        )

        written = synthesizer.write(FIGURES)

        self.assertFalse(written.accepted)
        self.assertEqual("", written.summary)

    def test_a_question_is_stripped_of_its_numbers(self) -> None:
        """And what is left reads as Korean. A placeholder that looks like
        content gets treated as content — `○○` was copied straight into the
        answer, so the scenario got no sentence at all."""
        self.assertEqual(
            redact("베트남에 3억 원 규모 장비를 수출합니다."),
            "베트남에 일정 금액 규모 장비를 수출합니다.",
        )
        self.assertNotIn("100,000", redact("10만 달러를 송금합니다."))


class PointerTests(unittest.TestCase):
    """The line §4.2[9] is not allowed to write.

    The sentence is given `figures()` and nothing else, so it cannot mention
    that support was judged — and it must not be able to. A model that could
    say "지원제도 후보가 있습니다" could also say "자격이 됩니다".
    """

    def test_it_counts_and_never_concludes(self) -> None:
        line = pointer(
            {
                "workers": {"skipped": {"compliance": "…"}},
                "support_candidates": [
                    {"status": "expert_confirmation_required"},
                    {"status": "insufficient_information"},
                    {"status": "insufficient_information"},
                ],
                "next_actions": [{"action": "consult"}],
            }
        )
        self.assertIn("지원제도 후보 1건", line)
        self.assertIn("정보 부족 2건", line)
        self.assertIn("다음 행동 1건", line)
        # No conclusion, only counts. `verdicts()` is not the check here — it
        # is a net for model-authored prose and it trips on the topic word
        # 지원제도, which is a subject and not a claim. What matters is that
        # nothing here decides anything.
        for conclusion in ("자격", "불필요", "해당 없음", "하세요", "권장"):
            self.assertNotIn(conclusion, line)

    def test_a_worker_that_did_not_run_is_not_mentioned(self) -> None:
        """Silence about compliance is not a clearance, and the pointer must
        not turn a skipped worker into a reported one."""
        line = pointer(
            {
                "workers": {"skipped": {"support": "…", "compliance": "…"}},
                "support_candidates": [],
            }
        )
        self.assertEqual("", line)

    def test_compliance_that_ran_and_found_nothing_still_says_so(self) -> None:
        line = pointer({"workers": {"skipped": {}}, "filing_obligations": []})
        self.assertIn("신고 검토", line)


class CeilingTests(unittest.TestCase):
    def test_a_slow_model_costs_the_sentence_and_not_the_answer(self) -> None:
        """Synthesis decorates figures that are already decided. The default
        model was answering a greeting in seventeen seconds and nothing caught
        it — the client's trace budget is a floor on the wait, not a ceiling,
        so the whole seventeen showed up on screen."""
        synthesizer = Synthesizer(api_key="x")

        def slow(**_):
            raise TimeoutError("timed out")

        synthesizer._client = type(
            "C", (), {"chat": type("M", (), {"completions": type("K", (), {"create": staticmethod(slow)})()})()}
        )()

        written = synthesizer.write(FIGURES)

        self.assertFalse(written.accepted)
        self.assertEqual("", written.summary)
        self.assertIn("실패", written.reason)

    def test_the_request_carries_a_deadline(self) -> None:
        synthesizer, completions = synthesizer_returning(
            {"figures_used": ["순노출: 100,000 USD"], "sentence": "순노출은 100,000 USD입니다."}
        )
        synthesizer.write(FIGURES)
        self.assertEqual(TIMEOUT_S, completions.request["timeout"])


class IntakePhrasingTests(unittest.TestCase):
    """§4.2[1]: the model supplies Korean, the slot reader supplies the list."""

    def test_asking_may_repeat_what_the_user_wrote(self) -> None:
        """Echoing "10만 달러" back to the person who just said it is
        confirmation, not the rounding §4.2[9] forbids."""
        allowed = ["amount: 100000", "10만 달러 수출이요"]
        self.assertEqual(check("수출 10만 달러의 결제일을 알려주세요.", allowed), "")

    def test_a_number_from_neither_the_user_nor_the_parse_is_caught(self) -> None:
        allowed = ["amount: 100000", "10만 달러 수출이요"]
        self.assertIn("146,630,000", check("146,630,000원이 됩니다.", allowed))

    def test_nothing_missing_means_nothing_to_ask(self) -> None:
        written = Synthesizer(api_key="x").ask_for([])
        self.assertFalse(written.accepted)

    def test_no_key_falls_back_to_the_question_list(self) -> None:
        """An empty `spoken` is what makes the screen list `questions` instead,
        so declining has to be silent and total."""
        written = Synthesizer(api_key="").ask_for(["amount"])
        self.assertEqual(written.summary, "")

    def test_every_missing_field_must_be_returned(self) -> None:
        synthesizer, _ = synthesizer_returning(
            {"acknowledgement": "안녕하세요.", "asked_fields": ["amount"]}
        )

        written = synthesizer.ask_for(["amount", "expected_payment_date"])

        self.assertFalse(written.accepted)
        self.assertEqual("", written.summary)

    def test_questions_are_rendered_from_the_exact_missing_fields(self) -> None:
        missing = ["amount", "expected_payment_date", "direction"]
        synthesizer, completions = synthesizer_returning(
            {
                "sentence": "안녕하세요. 거래 금액, 결제일, 수출입 여부를 알려주세요.",
                "asked_fields": missing,
            }
        )

        written = synthesizer.ask_for(missing)

        self.assertTrue(written.accepted)
        self.assertIn("안녕하세요", written.summary)
        schema = completions.request["response_format"]["json_schema"]
        field_schema = schema["schema"]["properties"]["asked_fields"]
        self.assertEqual(missing, field_schema["items"]["enum"])
        self.assertEqual(3, field_schema["minItems"])
        self.assertEqual(3, field_schema["maxItems"])


class WithoutAKeyTests(unittest.TestCase):
    def test_no_key_declines_rather_than_raising(self) -> None:
        """The product answers without prose. Refusing to start because an
        optional step is unavailable would make it a required one."""
        written = Synthesizer(api_key="").write(FIGURES)
        self.assertFalse(written.accepted)
        self.assertEqual(written.summary, "")

    def test_nothing_to_quote_is_declined_before_any_call(self) -> None:
        written = Synthesizer(api_key="x").write([])
        self.assertFalse(written.accepted)
        self.assertIn("수치가 없습니다", written.reason)


if __name__ == "__main__":
    unittest.main()
