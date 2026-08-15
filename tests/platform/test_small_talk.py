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


if __name__ == "__main__":
    unittest.main()
