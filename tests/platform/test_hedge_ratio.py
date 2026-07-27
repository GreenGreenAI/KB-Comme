import math
import unittest
from decimal import Decimal

from tradeflow.domain.enums import (
    AvailabilityStatus,
    FinancialInstrumentKind,
    HedgeMeasureCategory,
)
from tradeflow.domain.models import HedgeMeasure
from tradeflow.tools.hedge import UnusableMeasureError
from tradeflow.tools.hedge_ratio import (
    HEDGE_INSUFFICIENT,
    ExposureDirectionError,
    analyze_hedge,
    assert_within_bounds,
    breakeven,
    z_one_sided,
)


def _measure(contract_rate="1400.00", cost_rate="0.004") -> HedgeMeasure:
    return HedgeMeasure(
        "KSURE_FX",
        HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
        FinancialInstrumentKind.KSURE_FX_INSURANCE,
        AvailabilityStatus.AVAILABLE,
        contract_rate=Decimal(contract_rate),
        cost_rate=Decimal(cost_rate),
    )


BLOCKED = HedgeMeasure(
    "BANK_FORWARD",
    HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
    FinancialInstrumentKind.FORWARD,
    AvailabilityStatus.UNAVAILABLE,
    status_reasons=("담보 또는 신용라인 미보유",),
    contract_rate=Decimal("1400.00"),
)

EXPORTER = dict(
    net_exposure=Decimal("100000"),
    spot_rate=Decimal("1400.00"),
    baseline_profit=Decimal("20000000"),
    scaled_volatility=0.05,
)
IMPORTER = dict(
    net_exposure=Decimal("-100000"),
    spot_rate=Decimal("1400.00"),
    baseline_profit=Decimal("20000000"),
    scaled_volatility=0.05,
)


class QuantileTests(unittest.TestCase):
    def test_one_sided_quantile_matches_the_tabulated_value(self) -> None:
        self.assertAlmostEqual(1.645, z_one_sided(0.05), places=3)

    def test_alpha_outside_the_unit_interval_is_rejected(self) -> None:
        for alpha in (0.0, 1.0, -0.2):
            with self.subTest(alpha=alpha), self.assertRaises(ValueError):
                z_one_sided(alpha)


class GuardTests(unittest.TestCase):
    def test_unusable_measure_never_reaches_the_payoff(self) -> None:
        with self.assertRaises(UnusableMeasureError):
            analyze_hedge(BLOCKED, **EXPORTER)

    def test_zero_exposure_is_refused(self) -> None:
        with self.assertRaises(ExposureDirectionError):
            analyze_hedge(_measure(), **{**EXPORTER, "net_exposure": Decimal("0")})

    def test_ratio_outside_the_hard_constraint_is_rejected(self) -> None:
        assert_within_bounds([0.0, 0.5, 1.0])
        for ratio in (-0.1, 1.0001, 2.0):
            with self.subTest(ratio=ratio), self.assertRaises(ValueError):
                assert_within_bounds([ratio])


class AdverseDirectionTests(unittest.TestCase):
    def test_receipt_is_hurt_by_a_falling_rate(self) -> None:
        analysis = analyze_hedge(_measure(), **EXPORTER)

        self.assertLess(analysis.adverse_rate, EXPORTER["spot_rate"])

    def test_payment_is_hurt_by_a_rising_rate(self) -> None:
        analysis = analyze_hedge(_measure(), **IMPORTER)

        self.assertGreater(analysis.adverse_rate, IMPORTER["spot_rate"])

    def test_adverse_payoff_is_the_worst_of_the_three(self) -> None:
        for label, inputs in (("export", EXPORTER), ("import", IMPORTER)):
            with self.subTest(direction=label):
                unhedged = analyze_hedge(_measure(), **inputs).comparison[0]
                profits = {p.label: p.profit for p in unhedged.points}
                self.assertLess(profits["adverse"], profits["median"])
                self.assertLess(profits["median"], profits["favourable"])


class OptimalRatioTests(unittest.TestCase):
    def test_comfortable_floor_needs_no_hedge(self) -> None:
        analysis = analyze_hedge(
            _measure(), **EXPORTER, profit_floor=Decimal("-100000000")
        )

        self.assertEqual(0.0, analysis.optimal_ratio)
        self.assertTrue(analysis.sufficient)

    def test_ratio_never_exceeds_one(self) -> None:
        for floor in ("0", "10000000", "19000000", "19900000"):
            with self.subTest(floor=floor):
                analysis = analyze_hedge(
                    _measure(), **EXPORTER, profit_floor=Decimal(floor)
                )
                if analysis.optimal_ratio is not None:
                    self.assertGreaterEqual(analysis.optimal_ratio, 0.0)
                    self.assertLessEqual(analysis.optimal_ratio, 1.0)

    def test_optimal_ratio_just_reaches_the_floor(self) -> None:
        floor = Decimal("15000000")
        analysis = analyze_hedge(_measure(), **EXPORTER, profit_floor=floor)

        self.assertIsNotNone(analysis.optimal_ratio)
        optimal = next(s for s in analysis.comparison if s.ratio == analysis.optimal_ratio)
        self.assertGreaterEqual(optimal.at("adverse").profit, floor - Decimal("1"))

    def test_unreachable_floor_returns_status_and_alternatives(self) -> None:
        analysis = analyze_hedge(
            _measure(), **EXPORTER, profit_floor=Decimal("999999999")
        )

        self.assertIsNone(analysis.optimal_ratio)
        self.assertFalse(analysis.sufficient)
        self.assertEqual(HEDGE_INSUFFICIENT, analysis.status)
        self.assertIn("판가 전가", analysis.alternatives)
        self.assertIn("결제조건 조정", analysis.alternatives)

    def test_no_arbitrary_ratio_is_invented_when_insufficient(self) -> None:
        analysis = analyze_hedge(
            _measure(), **EXPORTER, profit_floor=Decimal("999999999")
        )

        self.assertIsNone(analysis.optimal_ratio)


class ComparisonTests(unittest.TestCase):
    def test_three_columns_are_presented_side_by_side(self) -> None:
        analysis = analyze_hedge(_measure(), **EXPORTER, profit_floor=Decimal("15000000"))

        self.assertEqual(3, len(analysis.comparison))
        self.assertEqual([0.0, analysis.optimal_ratio, 1.0], [s.ratio for s in analysis.comparison])

    def test_comparison_is_two_columns_when_optimal_is_an_endpoint(self) -> None:
        analysis = analyze_hedge(
            _measure(), **EXPORTER, profit_floor=Decimal("-100000000")
        )

        self.assertEqual([0.0, 1.0], [s.ratio for s in analysis.comparison])

    def test_full_hedge_narrows_the_spread(self) -> None:
        analysis = analyze_hedge(_measure(), **EXPORTER)
        unhedged, full = analysis.comparison[0], analysis.comparison[-1]

        def spread(scenario):
            return scenario.at("favourable").profit - scenario.at("adverse").profit

        self.assertLess(spread(full), spread(unhedged))

    def test_full_hedge_removes_rate_sensitivity(self) -> None:
        full = analyze_hedge(_measure(), **EXPORTER).comparison[-1]
        profits = {point.profit for point in full.points}

        self.assertEqual(1, len(profits))

    def test_importer_cost_is_deducted_from_profit(self) -> None:
        full = analyze_hedge(_measure(), **IMPORTER).comparison[-1]
        expected = (
            IMPORTER["baseline_profit"]
            - Decimal("0.004")
            * abs(IMPORTER["net_exposure"])
            * IMPORTER["spot_rate"]
        )

        self.assertEqual(expected.quantize(Decimal("1")), full.at("median").profit)

    def test_importer_optimal_ratio_uses_absolute_notional_for_cost(self) -> None:
        floor = Decimal("15000000")
        analysis = analyze_hedge(
            _measure(), **IMPORTER, profit_floor=floor
        )
        exposure = float(IMPORTER["net_exposure"])
        spot = float(IMPORTER["spot_rate"])
        baseline = float(IMPORTER["baseline_profit"])
        cost = 0.004
        adverse = spot * math.exp(z_one_sided(0.05) * IMPORTER["scaled_volatility"])
        intercept = baseline + exposure * (adverse - spot)
        expected_slope = (
            exposure * (float(_measure().contract_rate) - adverse)
            - cost * abs(exposure) * spot
        )
        expected = (float(floor) - intercept) / expected_slope

        self.assertAlmostEqual(expected, analysis.optimal_ratio, places=6)

    def test_result_carries_the_basis_needed_to_read_it(self) -> None:
        analysis = analyze_hedge(_measure(), **EXPORTER)

        self.assertEqual("ROUND_HALF_UP", analysis.rate_rounding)
        self.assertEqual("ROUND_HALF_UP", analysis.profit_rounding)
        self.assertEqual("KSURE_FX", analysis.measure_id)
        self.assertAlmostEqual(0.95, analysis.confidence_level, places=9)


class BreakevenTests(unittest.TestCase):
    def test_breakeven_matches_the_closed_form(self) -> None:
        result = breakeven(**EXPORTER)

        expected = 1400.0 - 20000000.0 / 100000.0
        self.assertEqual(Decimal(repr(expected)).quantize(Decimal("0.01")), result.rate)

    def test_receipt_loses_below_the_breakeven(self) -> None:
        result = breakeven(**EXPORTER)

        self.assertLess(result.rate, EXPORTER["spot_rate"])
        self.assertGreater(result.loss_probability, 0.0)
        self.assertLess(result.loss_probability, 1.0)

    def test_payment_loses_above_the_breakeven(self) -> None:
        result = breakeven(**IMPORTER)

        self.assertGreater(result.rate, IMPORTER["spot_rate"])
        self.assertGreater(result.loss_probability, 0.0)
        self.assertLess(result.loss_probability, 1.0)

    def test_probability_uses_the_tail_the_direction_implies(self) -> None:
        """A payer reads its loss from the upper tail, not the lower one.

        Taking the lower tail here would report ~0.996 — near-certain loss for
        a position that is comfortably profitable at the current rate.
        """
        from statistics import NormalDist

        result = breakeven(**IMPORTER)
        standardized = math.log(float(result.rate) / 1400.0) / 0.05
        lower_tail = NormalDist().cdf(standardized)

        self.assertGreater(lower_tail, 0.99)
        self.assertAlmostEqual(1.0 - lower_tail, result.loss_probability, places=9)
        self.assertLess(result.loss_probability, 0.5)

    def test_probability_matches_the_normal_cdf(self) -> None:
        result = breakeven(**EXPORTER)

        standardized = math.log(float(result.rate) / 1400.0) / 0.05
        from statistics import NormalDist

        self.assertAlmostEqual(
            NormalDist().cdf(standardized), result.loss_probability, places=6
        )

    def test_unreachable_breakeven_is_reported_as_none(self) -> None:
        result = breakeven(
            net_exposure=Decimal("100000"),
            spot_rate=Decimal("1400.00"),
            baseline_profit=Decimal("999000000"),
            scaled_volatility=0.05,
        )

        self.assertIsNone(result.rate)
        self.assertEqual(0.0, result.loss_probability)

    def test_payer_already_in_loss_is_certain_to_remain_in_loss(self) -> None:
        result = breakeven(
            net_exposure=Decimal("-100000"),
            spot_rate=Decimal("1400.00"),
            baseline_profit=Decimal("-200000000"),
            scaled_volatility=0.05,
        )

        self.assertIsNone(result.rate)
        self.assertEqual(1.0, result.loss_probability)

    def test_zero_volatility_at_zero_profit_is_not_a_loss(self) -> None:
        result = breakeven(
            net_exposure=Decimal("100000"),
            spot_rate=Decimal("1400.00"),
            baseline_profit=Decimal("0"),
            scaled_volatility=0.0,
        )

        self.assertEqual(Decimal("1400.00"), result.rate)
        self.assertEqual(0.0, result.loss_probability)

    def test_negative_volatility_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            breakeven(
                net_exposure=Decimal("100000"),
                spot_rate=Decimal("1400.00"),
                baseline_profit=Decimal("20000000"),
                scaled_volatility=-0.01,
            )

    def test_zero_exposure_is_refused(self) -> None:
        with self.assertRaises(ExposureDirectionError):
            breakeven(**{**EXPORTER, "net_exposure": Decimal("0")})


if __name__ == "__main__":
    unittest.main()
