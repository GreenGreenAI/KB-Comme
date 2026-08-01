import unittest

from tradeflow.tools.intent import read_intent
from tradeflow.tools.utterance_kind import ABOUT, GREETING, TOPIC, TRADE, read_kind


def kind(text: str, *, heard: dict[str, str] | None = None) -> str:
    """The reading as the endpoint performs it — both inputs come from the
    same sentence, and this module must not become a second, disagreeing
    reading of it."""
    return read_kind(text, heard=heard, topics=read_intent(text))


class KindTests(unittest.TestCase):
    """§4.2[1] counts the slots a trade is missing, and a greeting is missing
    all three exactly as a half-described trade is. Counting cannot tell them
    apart, so four different openings got one answer: 수출/수입 여부, 거래
    금액, 대금 지급 예정일을 알려주세요."""

    def test_a_greeting_is_a_greeting(self) -> None:
        for said in ("안녕", "안녕하세요", "안녕하세요!", "하이", "반가워요"):
            with self.subTest(said=said):
                self.assertEqual(GREETING, kind(said))

    def test_a_question_about_the_product_is_its_own_kind(self) -> None:
        for said in ("너 뭐 할 수 있어?", "이거 어떻게 쓰는 거야", "무슨 서비스야?"):
            with self.subTest(said=said):
                self.assertEqual(ABOUT, kind(said))

    def test_a_subject_with_no_trade_is_a_topic(self) -> None:
        self.assertEqual(TOPIC, kind("환율이 요즘 어때?"))
        self.assertEqual(TOPIC, kind("신고해야 할 게 있나요?"))

    def test_a_described_trade_wins_over_everything(self) -> None:
        """"안녕하세요, 10월에 10만 달러 받습니다" is a trade with a greeting
        attached. Answering the greeting would drop the one thing in the
        sentence that cost the user effort to write."""
        self.assertEqual(
            TRADE,
            kind(
                "안녕하세요, 10월 24일에 10만 달러 받기로 했어요",
                heard={"amount": "100000", "expected_payment_date": "2026-10-24"},
            ),
        )

    def test_a_greeting_that_goes_on_to_say_something_is_not_only_a_greeting(
        self,
    ) -> None:
        """What is left after the greeting words are removed decides. A
        sentence that opens politely and then says something keeps it."""
        self.assertNotEqual(
            GREETING, kind("안녕하세요, 수출 관련해서 여쭤볼 게 있는데요")
        )

    def test_an_unrecognised_sentence_still_asks_about_the_trade(self) -> None:
        """Neither a greeting, nor about the product, nor a subject we read.
        Asking what the trade is stays honest; the alternative is a guess
        about what they meant."""
        self.assertEqual(TRADE, kind("음"))


if __name__ == "__main__":
    unittest.main()
