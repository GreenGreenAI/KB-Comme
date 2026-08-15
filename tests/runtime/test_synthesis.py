import json
import unittest
from types import SimpleNamespace

from tradeflow.runtime.synthesis import (
    CONVERSE_LIMIT,
    NOT_SOCIAL,
    REFUSED_WORDING,
    check_retold,
    Synthesizer,
    check,
    check_bound,
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

    def test_dropping_a_required_unit_is_rejected(self) -> None:
        self.assertIn(
            "단위가 누락",
            check("순노출은 100,000입니다.", ["순노출: 100,000 USD"]),
        )

    def test_swapping_semantic_labels_is_rejected(self) -> None:
        sentence = (
            "순노출은 10,525,000 KRW이고 "
            "원화 수취액은 100,000 USD입니다."
        )
        self.assertIn("순노출", check_bound(sentence, FIGURES[:3:2]))


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

    def test_claimed_figure_must_keep_its_label_binding(self) -> None:
        synthesizer, _ = synthesizer_returning(
            {
                "figures_used": [
                    "순노출: 100,000 USD",
                    "그때 원화 수취액 차이: 10,525,000 KRW (감소)",
                ],
                "sentence": (
                    "순노출은 10,525,000 KRW이고 "
                    "원화 수취액 차이는 100,000 USD입니다."
                ),
            }
        )

        written = synthesizer.write(FIGURES)

        self.assertFalse(written.accepted)
        self.assertIn("순노출", written.reason)

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
        self.assertEqual(written, ["거래 순노출: 100,000 USD"])

    def test_the_label_says_what_the_figure_counted(self) -> None:
        """「거래」가 붙는 이유는 이 값이 세는 것이 거래뿐이기 때문이다. 명세
        §5.1의 `E`는 보유 외화까지 더하지만 이것은 Σ수취 − Σ지급이고, 이름
        없이 건네면 모델이 더 넓은 뜻으로 쓴다 — 검사를 통과하면서."""
        written = figures(
            {"cashflow_analysis": {"net_exposure": [{"currency": "USD", "amount": "40000"}]}}
        )

        self.assertTrue(written[0].startswith("거래 순노출: "))

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


class PointerLeadsWithTheReasonTests(unittest.TestCase):
    """A worker that did not run has no counts, so the pointer had nothing to
    say — and the answer opened on the exchange rate, to a company that had
    asked about 지원제도 and whose reason for not getting one was sitting in a
    fold two blocks down."""

    RESULT = {
        "workers": {"skipped": {"support": "기업규모와 신용 상태를 알려주시면 판정합니다"}},
        "support_candidates": [],
        "filing_obligations": [],
        "next_actions": [],
    }

    def test_the_reason_is_the_answer_when_that_worker_was_asked_about(self) -> None:
        self.assertEqual(
            "기업규모와 신용 상태를 알려주시면 판정합니다",
            pointer(self.RESULT, intent=("support",)),
        )

    def test_a_question_about_something_else_still_gets_the_counts(self) -> None:
        """The skipped worker keeps reporting itself in its own fold. Leading
        with it whatever was asked would make every answer about the thing the
        product could not do."""
        self.assertIn("신고 검토", pointer(self.RESULT, intent=("compliance",)))

    def test_no_intent_keeps_the_counts(self) -> None:
        self.assertIn("신고 검토", pointer(self.RESULT))

    def test_a_worker_that_ran_is_not_treated_as_skipped(self) -> None:
        ran = {
            "workers": {"skipped": {}},
            "support_candidates": [
                {"status": "expert_confirmation_required", "title": ""},
                {"status": "insufficient_information", "title": ""},
            ],
            "filing_obligations": [],
            "next_actions": [],
        }

        said = pointer(ran, intent=("support",))

        self.assertIn("지원제도 후보 1건", said)
        self.assertIn("정보 부족 1건", said)


class NamedVerdictTests(unittest.TestCase):
    """「받을 수 있는 지원제도가 있나요」 is answered by a name, not a count.

    「지원제도 후보 1건 · 정보 부족 2건」 is our bookkeeping: it says how many
    rows the reader is about to scroll past, which is not what was asked.
    """

    RESULT = {
        "workers": {"skipped": {}},
        "support_candidates": [
            {"status": "expert_confirmation_required", "title": "K-SURE 환변동보험"},
            {"status": "insufficient_information", "title": "K-SURE 수출신용보증"},
        ],
        "filing_obligations": [],
        "next_actions": [],
    }

    def test_it_names_what_the_rules_settled(self) -> None:
        said = pointer(self.RESULT, intent=("support",))

        self.assertIn("K-SURE 환변동보험은 조건을 충족합니다", said)
        self.assertIn("1개는 몇 가지를 더 알려주시면", said)

    def test_it_concludes_nothing_the_rules_did_not(self) -> None:
        """A pointer that could say 「신청하실 수 있습니다」 would be deciding.
        Naming what a rule named is reporting; the rest is the rule's."""
        said = pointer(self.RESULT, intent=("support",))

        self.assertNotIn("신청", said)
        self.assertNotIn("자격", said)

    def test_a_question_about_something_else_keeps_the_counts(self) -> None:
        self.assertIn("지원제도 후보", pointer(self.RESULT, intent=("hedge",)))

    def test_nothing_settled_falls_back_to_counting(self) -> None:
        open_only = {
            **self.RESULT,
            "support_candidates": [
                {"status": "insufficient_information", "title": "K-SURE 수출신용보증"}
            ],
        }

        self.assertIn("정보 부족 1건", pointer(open_only, intent=("support",)))


class NaturalProseTests(unittest.TestCase):
    """The binding check used to demand the label, not merely forbid the wrong
    one — every number had to appear beside the word we labelled it with.

    That rejected 「받을 100,000 USD가 결제일까지 열려 있습니다」: correct,
    natural, and saying nothing we did not compute. Every synthesised sentence
    failed it, the screen fell back to its own fixed prose, and every answer
    opened the same way. The check meant to keep the model honest had quietly
    removed it from the product.
    """

    FIGURES = [
        "순노출: 100,000 USD",
        "불리한 쪽 환율: 1361.05 (KRW per USD, 신뢰수준 0.9)",
        "그때 덜 받는 원화: 10,525,000 KRW",
    ]

    def test_a_figure_may_be_named_the_way_korean_names_it(self) -> None:
        self.assertEqual(
            "",
            check_bound(
                "받을 100,000 USD가 결제일까지 열려 있습니다. 불리한 쪽인 "
                "1361.05까지 가면 그때 손에 들어오는 원화가 10,525,000 KRW "
                "적어집니다.",
                self.FIGURES,
            ),
        )

    def test_quoting_our_own_labels_still_passes(self) -> None:
        self.assertEqual(
            "",
            check_bound(
                "순노출 100,000 USD, 불리한 쪽 환율 1361.05, "
                "그때 덜 받는 원화 10,525,000 KRW.",
                self.FIGURES,
            ),
        )

    def test_a_shared_word_is_not_a_claim_about_which_figure_is_meant(self) -> None:
        """「현재 환율」 shortens to 「환율」, which appears in any sentence about
        the adverse rate. Matching on the shortened form made every such
        sentence look like a misattribution."""
        figures = [
            "현재 환율: 1466.3 (KRW per USD, 한국은행 매매기준율 2026-07-27 기준)",
            "불리한 쪽 환율: 1361.05 (KRW per USD, 신뢰수준 0.9)",
        ]

        self.assertEqual(
            "",
            check_bound(
                "지금 환율은 1466.3이고, 불리한 쪽 환율은 1361.05입니다.", figures
            ),
        )


class ConverseTests(unittest.TestCase):
    """사교적 턴에 모델이 답하되, 판정과 수치는 여전히 못 만든다.

    이 경로가 안전한 이유는 위치다. 규칙이 먼저 읽고 거래 정보를 하나도 찾지
    못한 뒤에만 온다 — 그래서 모델이 어느 쪽으로 틀려도 최악이 오늘의 동작이다.
    """

    def reply(self, payload, *, holds_trade=False):
        synthesizer, _ = synthesizer_returning(payload)
        return synthesizer.converse("고마워요", holds_trade=holds_trade)

    def test_small_talk_gets_an_answer(self) -> None:
        said = self.reply({"general": True, "sentence": "고맙습니다. 편하게 말씀해 주세요."})

        self.assertTrue(said.accepted)
        self.assertEqual("고맙습니다. 편하게 말씀해 주세요.", said.sentence)

    def test_a_feature_request_is_handed_back(self) -> None:
        """기능을 쓰려는 말로 읽었다면 이 경로가 답할 일이 아니다 — 기존 분기가
        답한다. 모델이 판단하는 것은 그 하나뿐이다."""
        said = self.reply({"general": False, "sentence": ""})

        self.assertFalse(said.accepted)
        self.assertEqual(NOT_SOCIAL, said.reason)

    def test_it_may_not_judge(self) -> None:
        said = self.reply({"general": True, "sentence": "네, 이 정도면 안전합니다."})

        self.assertFalse(said.accepted)
        self.assertTrue(said.reason.startswith(REFUSED_WORDING))
        self.assertIn("안전합니다", said.reason)

    def test_it_may_not_carry_a_figure(self) -> None:
        """수치가 주어지지 않은 경로다. 문장에 숫자가 있다면 모델이 만든
        것이거나 사용자 문장에서 옮겨 온 것이고, 둘 다 도구가 확인해 준 값처럼
        읽힌다."""
        said = self.reply({"general": True, "sentence": "말씀하신 100,000 USD 잘 받았습니다."})

        self.assertFalse(said.accepted)
        self.assertIn("수치", said.reason)

    def test_a_paragraph_is_not_a_social_reply(self) -> None:
        """인사에 세 문장으로 답했다면 인사에 답한 것이 아니라 무언가를
        설명하기 시작한 것이고, 설명이야말로 이 경로에 근거가 없는 말이다."""
        said = self.reply({"general": True, "sentence": "네. " * CONVERSE_LIMIT})

        self.assertFalse(said.accepted)
        self.assertTrue(said.reason.startswith(REFUSED_WORDING))

    def test_the_refusal_is_told_apart_from_a_feature_request(self) -> None:
        """호출자가 두 경우에 다르게 행동해야 한다 — 하나는 계산 경로로
        넘기고, 하나는 자기 문장으로 답한다."""
        judged = self.reply({"general": True, "sentence": "이 정도면 안전합니다."})
        traded = self.reply({"general": False, "sentence": ""})

        self.assertTrue(judged.reason.startswith(REFUSED_WORDING))
        self.assertFalse(traded.reason.startswith(REFUSED_WORDING))

    def test_what_is_on_screen_reaches_the_prompt(self) -> None:
        """화면에 거래가 있는데 거래를 알려 달라고 하면 보지 않은 것이다."""
        synthesizer, completions = synthesizer_returning(
            {"general": True, "sentence": "네, 말씀해 주세요."}
        )
        synthesizer.converse("고마워요", holds_trade=True)

        sent = completions.request["messages"][0]["content"]
        self.assertIn("거래를 알려 달라고 하지 마세요", sent)

    def test_no_key_declines_rather_than_raises(self) -> None:
        self.assertFalse(Synthesizer(api_key=None).converse("고마워요", holds_trade=False).accepted)


if __name__ == "__main__":
    unittest.main()


class RetoldContractTests(unittest.TestCase):
    """「정보를 추가생성하지 말고 결과만 조합하라」 is a request when it is
    written in a prompt and a contract when it is checked here.

    The same model was asked not to instruct and answered 「담당 부서로
    연결해 드리겠습니다」; asked not to calculate and answered 「1억 3,610만
    5,000원」; and asked to keep it short, dropped two of four judgements.
    Each was caught by a check, none by the instruction.
    """

    SOURCE = (
        "K-SURE 일반형 수출 환변동보험은 조건을 충족합니다. 확인한 조건은 5가지입니다. "
        "다음은 한국무역보험공사 상담 및 청약입니다. 필요서류는 6건입니다."
    )
    SUBJECTS = ("K-SURE 일반형 수출 환변동보험",)

    def test_a_faithful_rewrite_passes(self) -> None:
        self.assertEqual(
            "",
            check_retold(
                "K-SURE 일반형 수출 환변동보험은 조건 5가지를 충족합니다. "
                "한국무역보험공사 상담 및 청약에 필요서류 6건이 듭니다.",
                self.SOURCE,
                self.SUBJECTS,
            ),
        )

    def test_an_institution_that_was_not_judged_is_refused(self) -> None:
        self.assertIn(
            "KOTRA",
            check_retold(
                "K-SURE 일반형 수출 환변동보험 외에 KOTRA 수출바우처도 있습니다.",
                self.SOURCE,
                self.SUBJECTS,
            ),
        )

    def test_a_number_the_model_worked_out_is_refused(self) -> None:
        """Arithmetically right and an invention by the only definition that
        matters: it was not in what the rules produced."""
        self.assertIn(
            "11",
            check_retold(
                "K-SURE 일반형 수출 환변동보험은 모두 11가지를 요구합니다.",
                self.SOURCE,
                self.SUBJECTS,
            ),
        )

    def test_a_dropped_judgement_is_refused(self) -> None:
        """Invention is the loud failure; omission is the quiet one. A summary
        that leaves a product out reads well and leaves the company believing
        it was never considered."""
        self.assertIn(
            "환변동보험",
            check_retold(
                "한국무역보험공사 상담 및 청약에 필요서류 6건이 듭니다.",
                self.SOURCE,
                self.SUBJECTS,
            ),
        )

    def test_a_shortened_product_name_is_not_an_omission(self) -> None:
        self.assertEqual(
            "",
            check_retold(
                "환변동보험은 조건 5가지를 충족합니다. "
                "한국무역보험공사 상담 및 청약에 필요서류 6건이 듭니다.",
                self.SOURCE,
                self.SUBJECTS,
            ),
        )


class RequiredPhraseTests(unittest.TestCase):
    """Some sentences may not be paraphrased at all.

    §5.5 rests on 「신고가 불필요하다는 판정은 아닙니다」, and the first rewrite
    allowed near it shortened it away — shorter, better read, and leaving the
    company believing it has no filing duty. A subject can be renamed; this
    cannot be reworded.
    """

    SOURCE = (
        "양자간 상계면 외국환은행에 보고합니다. "
        "말씀해 주신 것으로는 해당 여부를 알 수 없는 규칙이 14건 더 있습니다. "
        "신고가 불필요하다는 판정은 아닙니다."
    )
    KEEP = ("신고가 불필요하다는 판정은 아닙니다",)

    def test_carrying_it_word_for_word_passes(self) -> None:
        self.assertEqual(
            "",
            check_retold(
                "양자간 상계면 외국환은행에 보고합니다. 나머지 14건은 아직 "
                "알 수 없습니다. 신고가 불필요하다는 판정은 아닙니다.",
                self.SOURCE,
                (),
                self.KEEP,
            ),
        )

    def test_shortening_it_away_is_refused(self) -> None:
        self.assertIn(
            "그대로 옮겨야 하는 문장",
            check_retold(
                "양자간 상계면 외국환은행에 보고합니다. 나머지 14건은 아직 "
                "알 수 없습니다.",
                self.SOURCE,
                (),
                self.KEEP,
            ),
        )

    def test_rewording_it_is_refused(self) -> None:
        """「신고 의무가 없다는 뜻은 아닙니다」 means the same thing and is not
        the sentence. The rule is verbatim because judging the paraphrase is
        the thing this check exists to avoid.

        Which guard refuses it is not the point — this one is caught by the
        verdict check first, because 의무 is a word the source never used. The
        property under test is that it does not get through.
        """
        self.assertNotEqual(
            "",
            check_retold(
                "양자간 상계면 외국환은행에 보고합니다. 나머지 14건은 신고 "
                "의무가 없다는 뜻은 아닙니다.",
                self.SOURCE,
                (),
                self.KEEP,
            ),
        )
