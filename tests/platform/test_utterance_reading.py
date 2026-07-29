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


class DateTests(unittest.TestCase):
    def test_a_date_given_in_months_is_still_given(self) -> None:
        """"2달 후 $100,000를 송금해야 하는데" met "날짜를 알려주세요". The date
        was stated; asking again reads as not having listened."""
        # Counted from AS_OF, 2026-07-28.
        self.assertEqual(
            "2026-09-28", read("2달 후 미국에 $100,000 송금")["expected_payment_date"]
        )
        self.assertEqual(
            "2026-09-28", read("두 달 뒤 10만 달러 수입")["expected_payment_date"]
        )
        self.assertEqual(
            "2026-10-28", read("3개월 후 20만 달러 수취")["expected_payment_date"]
        )
        self.assertEqual(
            "2026-09-11", read("45일 뒤 5만 달러 결제")["expected_payment_date"]
        )

    def test_a_month_end_does_not_roll_over(self) -> None:
        """31 January plus one month is 28 February, not 3 March — a rolled
        date moves the cashflow event past a month end."""
        from tradeflow.tools.utterance import read_utterance

        heard = read_utterance("다음 달 10만 달러 수입", as_of=date(2026, 1, 31))
        self.assertEqual("2026-02-28", heard["expected_payment_date"])

    def test_an_amount_is_never_eaten_as_a_day(self) -> None:
        """`내년 3월 10만 달러` was read as March 10th. The amount became part
        of the date and was then reported as understood, which is worse than
        not reading it: the screen showed a settlement date nobody gave."""
        heard = read("내년 3월 10만 달러 수입")
        self.assertNotIn("expected_payment_date", heard)
        self.assertEqual("100000", heard["amount"])

    def test_a_real_day_still_reads(self) -> None:
        self.assertEqual(
            "2027-03-10", read("3월 10일 10만 달러 수입")["expected_payment_date"]
        )
        self.assertEqual(
            "2026-10-24", read("10/24에 10만 달러 수출")["expected_payment_date"]
        )


class DateRoleTests(unittest.TestCase):
    """A sentence carries several dates and they are not interchangeable.

    Mishearing is worse than not hearing. A gap asks a question; a misread
    settlement date produces a whole answer — exposure, band, hedge — built on
    a day nobody gave, and reports it as understood.
    """

    def test_a_shipment_date_is_not_a_settlement_date(self) -> None:
        heard = read("9월 3일에 선적합니다")
        self.assertEqual("2026-09-03", heard["expected_shipment_date"])
        self.assertNotIn("expected_payment_date", heard)

    def test_a_contract_date_is_not_a_settlement_date(self) -> None:
        heard = read("7월 1일에 계약했습니다")
        self.assertEqual("2026-07-01", heard["contract_date"])
        self.assertNotIn("expected_payment_date", heard)

    def test_a_contract_is_dated_backwards(self) -> None:
        """It was signed before today. Reading every bare month-day forward
        made "7월 1일에 계약했습니다" a contract dated next year."""
        self.assertEqual("2025-12-01", read("12월 1일에 계약했습니다")["contract_date"])

    def test_each_date_keeps_its_own_qualifier(self) -> None:
        """The words between two dates belong to the earlier one — Korean puts
        the qualifier after. Reading backwards let the second date take the
        first one's 선적 and the settlement date was lost."""
        heard = read("9월 3일 선적, 10월 24일 결제")
        self.assertEqual("2026-09-03", heard["expected_shipment_date"])
        self.assertEqual("2026-10-24", heard["expected_payment_date"])

    def test_it_holds_without_punctuation_between_the_clauses(self) -> None:
        heard = read("12월 1일에 계약했고 3월 20일에 결제합니다")
        self.assertEqual("2025-12-01", heard["contract_date"])
        self.assertEqual("2027-03-20", heard["expected_payment_date"])

    def test_a_qualifier_before_the_first_date_still_counts(self) -> None:
        self.assertEqual("2026-07-01", read("계약일은 7월 1일입니다")["contract_date"])


class CurrencyTests(unittest.TestCase):
    def test_a_named_currency_reaches_the_slot_reader(self) -> None:
        """§2.4 fixed the MVP to USD and `read_slots` refuses anything else —
        but only when the currency reaches it. Reading none let a euro trade
        default to dollars and be analysed as one, which bypasses the refusal
        rather than passing it."""
        self.assertEqual("EUR", read("유로로 15만 유로 받아요")["currency"])
        self.assertEqual("JPY", read("엔화로 결제받습니다")["currency"])
        self.assertEqual("USD", read("10만 달러 수출")["currency"])


if __name__ == "__main__":
    unittest.main()
