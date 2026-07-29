import unittest
from datetime import date
from decimal import Decimal

from tradeflow.tools.utterance import krw_amount, read_utterance

AS_OF = date(2026, 7, 28)


def read(text: str) -> dict:
    return read_utterance(text, as_of=AS_OF)


class CountryTests(unittest.TestCase):
    def test_a_named_country_is_heard(self) -> None:
        """§5.4 reads `counterparty.country_restricted`, and the country it
        needs was being dropped on the floor — a trade that named Vietnam was
        analysed as a trade that named nowhere."""
        self.assertEqual("VN", read("베트남에 장비를 수출합니다")["country"])
        self.assertEqual("BR", read("브라질 바이어와 D/A 거래")["country"])

    def test_an_unlisted_country_stays_a_question(self) -> None:
        """The map is the partners this product was designed against, not a
        world list. Guessing at an unlisted name would be worse than asking."""
        self.assertNotIn("country", read("에스와티니로 수출합니다"))


class KrwAmountTests(unittest.TestCase):
    def test_a_won_figure_is_heard_but_is_not_the_exposure(self) -> None:
        """§5.1 measures foreign currency, so a KRW contract carries none —
        the parser is right to keep it out of `amount`. What was wrong was
        saying nothing: "3억 원 규모" met "거래 금액이 얼마인가요? (달러 기준)",
        which reads as not having been heard."""
        sentence = "베트남에 3억 원 규모의 장비를 수출합니다"
        self.assertNotIn("amount", read(sentence))
        self.assertEqual(Decimal("300000000"), krw_amount(sentence))

    def test_a_foreign_amount_still_wins(self) -> None:
        heard = read("10만 달러를 수출하고 원화로 3억 원을 받습니다")
        self.assertEqual("100000", heard["amount"])

    def test_korean_magnitudes_work_in_dollars(self) -> None:
        """`1천만 달러` is how people write ten million dollars, and it was not
        read at all: the pattern took one magnitude, so `1` + `천` matched and
        `만 달러` did not follow."""
        self.assertEqual("300000000", read("3억 달러 수출")["amount"])
        self.assertEqual("10000000", read("1천만 달러 수출")["amount"])
        self.assertEqual("3000000", read("3백만 달러 수입")["amount"])

    def test_a_compound_magnitude_is_summed_not_truncated(self) -> None:
        """Under-reading is worse than not reading — the figure would look
        heard and be wrong. `1억 5천만` is 150,000,000, never 100,000,000."""
        self.assertEqual("150000000", read("1억 5천만 달러 수출")["amount"])
        self.assertEqual(Decimal("150000000"), krw_amount("1억 5천만 원 규모"))

    def test_a_sentence_without_won_offers_nothing(self) -> None:
        self.assertIsNone(krw_amount("10만 달러 수출"))


if __name__ == "__main__":
    unittest.main()
