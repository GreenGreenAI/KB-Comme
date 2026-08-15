"""거래가 화면에 있어도 인사는 인사다.

`supplied_trade`는 「거래를 버리면 안 된다」를 지키려고 있었는데, 인사에 답하는
일과 거래를 버리는 일이 한 조건에 묶여 있었다. 그래서 대화 중간의 「안녕」이
계산 경로로 흘러 들어갔고, 아무것도 읽지 못한 턴이 되어 「그 문장에서는 거래
정보를 읽지 못해 계산이 달라지지 않았습니다」로 돌아왔다.

거래는 어차피 사라지지 않는다 — 이 응답은 워커를 돌리지 않고 무엇도 판정하지
않으며, 거래 목록은 화면이 들고 있다.
"""

import unittest

from tradeflow.web.app import AnalyzeRequest, analyze_endpoint

CASE = {
    "direction": "수출",
    "amount": "100000",
    "expected_payment_date": "2026-10-24",
    "currency": "USD",
}


def answer(utterance: str, *, cases: list[dict] | None = None) -> dict:
    return analyze_endpoint(
        AnalyzeRequest(
            utterance=utterance,
            cases=cases or [],
            as_of="2026-08-15",
        )
    )


class GreetingTests(unittest.TestCase):
    def test_a_greeting_is_answered_before_any_trade_is_described(self) -> None:
        said = answer("안녕")

        self.assertEqual("said", said["status"])
        self.assertTrue(said["spoken"].startswith("안녕하세요"))

    def test_a_greeting_is_still_a_greeting_with_a_trade_on_screen(self) -> None:
        said = answer("안녕", cases=[CASE])

        self.assertEqual("said", said["status"])
        # 계산 경로로 갔다면 이 문장이 나온다.
        self.assertNotIn("거래 정보를 읽지 못해", said.get("spoken", ""))

    def test_it_does_not_ask_for_a_trade_it_already_has(self) -> None:
        """화면 위에 거래가 있는데 「거래를 말씀해 주세요」라고 하면 보지 않은
        것이다. 같은 인사라도 첫 대면과 대화 중간은 다른 자리다."""
        first = answer("안녕")["spoken"]
        later = answer("안녕", cases=[CASE])["spoken"]

        self.assertIn("거래를 편하게 말씀해 주세요", first)
        self.assertNotIn("거래를 편하게 말씀해 주세요", later)

    def test_asking_what_it_does_never_needs_a_trade(self) -> None:
        said = answer("뭐 할 수 있어?", cases=[CASE])

        self.assertEqual("said", said["status"])
        self.assertIn("계산하고 판정합니다", said["spoken"])


class StillCalculatedTests(unittest.TestCase):
    """무엇이 이 경로로 새면 안 되는지."""

    def test_a_follow_up_about_the_trade_is_calculated(self) -> None:
        """「왜?」는 앞 판정의 근거를 묻는 말이고, 근거는 패킷 안에 있다."""
        self.assertNotEqual("said", answer("왜?", cases=[CASE])["status"])

    def test_a_subject_question_with_a_trade_is_calculated(self) -> None:
        """거래를 앞에 두고 「환율은?」을 물었다면 그 거래에 대한 질문이다."""
        self.assertNotEqual("said", answer("환율은 어때?", cases=[CASE])["status"])

    def test_a_described_trade_is_never_small_talk(self) -> None:
        said = answer("12월 3일에 수출대금 15만 달러 받아요", cases=[CASE])

        self.assertNotEqual("said", said["status"])


class KeylessTests(unittest.TestCase):
    """키가 없으면 사교적 합성은 사양하고, 나머지는 그대로 돈다.

    이 파일의 다른 모든 검사가 키 없이 통과한다는 것이 그 증거다 — 인사와 제품
    질문은 규칙이 쓰고, 모델은 문구를 다듬을 뿐이다."""

    def test_courtesy_without_a_key_falls_back_rather_than_failing(self) -> None:
        said = answer("고마워요", cases=[CASE])

        # 모델이 없으니 사교적 답변은 안 나오지만, 요청이 깨지지도 않는다.
        self.assertIn(said["status"], {"said", "ready", "needs_input"})


class FunnelEntryTests(unittest.TestCase):
    """깔때기는 거래를 읽었을 때만 열린다.

    `read_kind`의 기본값이 TRADE였을 때 깔때기는 아무도 규칙을 써 두지 않은
    모든 문장의 기본 목적지였다. 「고마워」에 금액과 결제일과 수출입 여부를
    물었던 것이 그 결과다.
    """

    def test_an_unrecognised_sentence_is_not_called_a_trade(self) -> None:
        from tradeflow.tools.utterance_kind import UNCLEAR, read_kind

        self.assertEqual(UNCLEAR, read_kind("고마워", heard={}, topics=()))

    def test_the_funnel_says_it_did_not_understand_first(self) -> None:
        """읽지 못한 문장 뒤에 질문 세 개가 곧바로 오면 요구로 읽힌다.
        못 알아들었다는 말이 먼저 있어야 그다음 질문이 요청이 된다."""
        said = answer("asdfgh")

        self.assertEqual("needs_input", said["status"])
        self.assertIn("이해하지 못했습니다", said["unread"])

    def test_a_read_trade_gets_no_apology(self) -> None:
        """읽은 문장에는 못 알아들었다고 하지 않는다."""
        said = answer("10월 24일 수출 10만 달러")

        self.assertEqual("", said.get("unread", ""))

    def test_slots_alone_open_the_funnel(self) -> None:
        """방향만으로는 거래가 아니다 — 제도 이름에도 수출·수입이 들어 있다."""
        from tradeflow.tools.utterance_kind import TRADE, read_kind

        self.assertEqual(
            TRADE, read_kind("10만 달러", heard={"amount": "100000"}, topics=())
        )


class ModelJudgementTests(unittest.TestCase):
    """모델이 판단하는 것은 하나뿐이다 — 일반 대화인가, 기능을 쓰려는 말인가.

    갈래를 셋으로 늘려 「무엇을 할 수 있는지 묻는 말」까지 구분시켜 봤다가
    되돌렸다. 판단을 하나 더 얹는 것이고, 그 답은 어차피 모델이 쓰지 않는다 —
    제품 소개는 규칙팩을 세어서 조립되고, 모델은 그것을 쓰지 못하게 막혀 있다.
    """

    def test_the_model_is_asked_one_thing(self) -> None:
        from tradeflow.runtime.synthesis import CONVERSE_SCHEMA

        properties = CONVERSE_SCHEMA["schema"]["properties"]
        self.assertEqual({"general", "sentence"}, set(properties))
        self.assertEqual("boolean", properties["general"]["type"])

    def test_the_model_is_told_not_to_describe_the_product(self) -> None:
        """소개 문장은 규칙에서 조립된다. 모델이 자유롭게 쓰면 자기가 설명하는
        규칙보다 오래 살아남는 마케팅 문장이 된다."""
        from tradeflow.runtime.synthesis import CONVERSE_INSTRUCTION

        self.assertIn("무엇을 할 수 있는지 설명하지 마세요", CONVERSE_INSTRUCTION)

    def test_the_product_describes_itself_from_its_rulepacks(self) -> None:
        """`_ABOUT`이 소개가 나오는 유일한 길이고, 그 내용은 조립된다."""
        from tradeflow.runtime import coverage

        said = answer("뭐 할 수 있어?")

        self.assertEqual("said", said["status"])
        self.assertIn(coverage.statement("support"), said["spoken"])


if __name__ == "__main__":
    unittest.main()
