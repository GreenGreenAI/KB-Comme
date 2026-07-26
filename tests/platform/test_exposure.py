import unittest
from datetime import date
from decimal import Decimal

from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.tools.exposure import analyze_exposure


class ExposureTests(unittest.TestCase):
    def test_maturity_gap_is_not_hidden_by_later_export_receipt(self) -> None:
        program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Test"),
            (
                TradeCase(
                    "I1", TradeDirection.IMPORT, "USD", Decimal("60000"),
                    date(2026, 8, 25), PaymentMethod.TT,
                ),
                TradeCase(
                    "E1", TradeDirection.EXPORT, "USD", Decimal("100000"),
                    date(2026, 10, 24), PaymentMethod.TT,
                ),
            ),
            {"USD": Decimal("20000")},
            date(2026, 7, 26),
        )

        exposure = analyze_exposure(program)[0]

        self.assertEqual(Decimal("60000"), exposure.economic_offset)
        self.assertEqual(Decimal("40000"), exposure.trade_net_exposure)
        self.assertEqual(Decimal("40000"), exposure.peak_funding_gap)
        self.assertEqual(Decimal("60000"), exposure.ending_balance)
        self.assertEqual(Decimal("-40000"), exposure.timeline[0].running_balance)

    def test_offset_is_not_claimed_as_matched_when_receipt_comes_later(self) -> None:
        program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Test"),
            (
                TradeCase(
                    "I1", TradeDirection.IMPORT, "USD", Decimal("60000"),
                    date(2026, 8, 25), PaymentMethod.TT,
                ),
                TradeCase(
                    "E1", TradeDirection.EXPORT, "USD", Decimal("100000"),
                    date(2026, 10, 24), PaymentMethod.TT,
                ),
            ),
            {"USD": Decimal("20000")},
            date(2026, 7, 26),
        )

        exposure = analyze_exposure(program)[0]

        self.assertEqual(Decimal("60000"), exposure.economic_offset)
        self.assertEqual(Decimal("0"), exposure.maturity_matched_amount)

    def test_receipt_before_payment_is_matched(self) -> None:
        program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Test"),
            (
                TradeCase(
                    "E1", TradeDirection.EXPORT, "USD", Decimal("100000"),
                    date(2026, 8, 25), PaymentMethod.TT,
                ),
                TradeCase(
                    "I1", TradeDirection.IMPORT, "USD", Decimal("60000"),
                    date(2026, 10, 24), PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 26),
        )

        exposure = analyze_exposure(program)[0]

        self.assertEqual(Decimal("60000"), exposure.economic_offset)
        self.assertEqual(Decimal("60000"), exposure.maturity_matched_amount)
        self.assertEqual(Decimal("0"), exposure.peak_funding_gap)

    def test_import_heavy_program_keeps_negative_net_exposure(self) -> None:
        program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Test"),
            (
                TradeCase(
                    "E1", TradeDirection.EXPORT, "USD", Decimal("40000"),
                    date(2026, 8, 25), PaymentMethod.TT,
                ),
                TradeCase(
                    "I1", TradeDirection.IMPORT, "USD", Decimal("100000"),
                    date(2026, 10, 24), PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 26),
        )

        exposure = analyze_exposure(program)[0]

        self.assertEqual(Decimal("-60000"), exposure.trade_net_exposure)

    def test_same_date_settles_payment_first(self) -> None:
        program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Test"),
            (
                TradeCase(
                    "A_EXPORT", TradeDirection.EXPORT, "USD", Decimal("50000"),
                    date(2026, 8, 25), PaymentMethod.TT,
                ),
                TradeCase(
                    "Z_IMPORT", TradeDirection.IMPORT, "USD", Decimal("50000"),
                    date(2026, 8, 25), PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 26),
        )

        exposure = analyze_exposure(program)[0]

        self.assertEqual("Z_IMPORT", exposure.timeline[0].case_id)
        self.assertEqual(Decimal("50000"), exposure.peak_funding_gap)
        self.assertEqual(Decimal("0"), exposure.maturity_matched_amount)


if __name__ == "__main__":
    unittest.main()
