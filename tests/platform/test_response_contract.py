import unittest
from datetime import date
from decimal import Decimal

from tradeflow.contracts.response import project_cashflow_analysis
from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.tools.exposure import analyze_exposure


def _baseline_program() -> TradeProgram:
    return TradeProgram(
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


class ResponseContractTests(unittest.TestCase):
    def test_projection_preserves_tool_figures_exactly(self) -> None:
        exposures = analyze_exposure(_baseline_program())
        projected = project_cashflow_analysis(exposures)

        source = exposures[0]
        self.assertEqual(source.economic_offset, projected["natural_hedge_amount"][0]["amount"])
        self.assertEqual(
            source.maturity_matched_amount,
            projected["maturity_matched_amount"][0]["amount"],
        )
        self.assertEqual(source.trade_net_exposure, projected["net_exposure"][0]["amount"])
        self.assertEqual(source.peak_funding_gap, projected["funding_gap"][0]["peak_amount"])
        self.assertEqual(len(source.timeline), len(projected["events"]))

    def test_offset_and_matched_amount_are_reported_together(self) -> None:
        """The contract must not let an unusable offset stand on its own."""
        projected = project_cashflow_analysis(analyze_exposure(_baseline_program()))

        self.assertEqual(Decimal("60000"), projected["natural_hedge_amount"][0]["amount"])
        self.assertEqual(Decimal("0"), projected["maturity_matched_amount"][0]["amount"])
        self.assertEqual(Decimal("40000"), projected["funding_gap"][0]["peak_amount"])

    def test_net_exposure_keeps_direction(self) -> None:
        program = TradeProgram(
            "P2",
            CompanyProfile("C1", "Test"),
            (
                TradeCase(
                    "I1", TradeDirection.IMPORT, "USD", Decimal("100000"),
                    date(2026, 9, 1), PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 26),
        )

        projected = project_cashflow_analysis(analyze_exposure(program))

        self.assertEqual(Decimal("-100000"), projected["net_exposure"][0]["amount"])


if __name__ == "__main__":
    unittest.main()
