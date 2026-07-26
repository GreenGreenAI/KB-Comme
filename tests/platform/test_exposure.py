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


if __name__ == "__main__":
    unittest.main()
