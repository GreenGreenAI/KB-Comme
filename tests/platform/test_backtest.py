import math
import unittest
from datetime import date, timedelta
from decimal import Decimal

from tradeflow.tools.backtest import (
    TARGET_RANGE,
    InsufficientHistoryError,
    measure_coverage,
)


def _series(rates: list[float]) -> list[tuple[date, Decimal]]:
    start = date(2020, 1, 1)
    return [
        (start + timedelta(days=i), Decimal(repr(round(rate, 6))))
        for i, rate in enumerate(rates)
    ]


def _alternating(days: int, step: float, start: float = 1400.0) -> list[float]:
    rates = [start]
    for i in range(days - 1):
        rates.append(rates[-1] * math.exp(step * (1 if i % 2 else -1)))
    return rates


class HistoryRequirementTests(unittest.TestCase):
    def test_series_shorter_than_window_plus_horizon_is_refused(self) -> None:
        with self.assertRaises(InsufficientHistoryError) as caught:
            measure_coverage(
                _series(_alternating(50, 0.004)),
                horizon_business_days=10,
                window=60,
            )

        self.assertIn("60", str(caught.exception))
        self.assertIn("50", str(caught.exception))

    def test_exactly_enough_history_yields_one_origin(self) -> None:
        result = measure_coverage(
            _series(_alternating(31, 0.004)),
            horizon_business_days=10,
            window=20,
        )

        self.assertEqual(1, result.tested)

    def test_step_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            measure_coverage(
                _series(_alternating(200, 0.004)),
                horizon_business_days=10,
                step=0,
            )


class NoLookaheadTests(unittest.TestCase):
    def test_estimate_never_sees_the_future_it_is_tested_against(self) -> None:
        """A flat past must produce a collapsed band, however wild the future.

        If the window reached past the origin, the jump would widen the band
        and the miss below would disappear.
        """
        flat = [1400.0] * 21
        crash = [900.0] * 10
        result = measure_coverage(
            _series(flat + crash), horizon_business_days=10, window=20
        )

        self.assertEqual(1, result.tested)
        self.assertEqual(0, result.covered)
        self.assertEqual(1, result.below)


class CoverageCountingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.series = _series(_alternating(400, 0.004))

    def test_counts_partition_the_sample(self) -> None:
        result = measure_coverage(self.series, horizon_business_days=20, window=60)

        self.assertEqual(
            result.tested, result.covered + result.below + result.above
        )
        self.assertGreater(result.tested, 0)

    def test_coverage_is_the_covered_share(self) -> None:
        result = measure_coverage(self.series, horizon_business_days=20, window=60)

        self.assertAlmostEqual(
            result.covered / result.tested, result.coverage, places=12
        )

    def test_origins_are_reported(self) -> None:
        result = measure_coverage(self.series, horizon_business_days=20, window=60)

        self.assertLess(result.first_origin, result.last_origin)
        self.assertEqual(self.series[60][0], result.first_origin)

    def test_step_thins_the_sample(self) -> None:
        dense = measure_coverage(self.series, horizon_business_days=20, window=60)
        sparse = measure_coverage(
            self.series, horizon_business_days=20, window=60, step=5
        )

        self.assertLess(sparse.tested, dense.tested)

    def test_perfect_coverage_is_also_outside_the_target(self) -> None:
        """The target is two-sided: a band that never misses is too wide.

        A perfectly mean-reverting series is covered every time, and that is a
        calibration failure in the other direction — the stated 90% would be
        understating how confident the band actually is.
        """
        result = measure_coverage(self.series, horizon_business_days=20, window=60)

        self.assertEqual(1.0, result.coverage)
        self.assertGreater(result.coverage, TARGET_RANGE[1])
        self.assertFalse(result.within_target)


class TargetTests(unittest.TestCase):
    def test_target_range_matches_the_specification(self) -> None:
        self.assertEqual((0.85, 0.95), TARGET_RANGE)

    def test_coverage_outside_the_range_is_reported_as_missing_target(self) -> None:
        flat = [1400.0] * 81
        drift = [1400.0 * math.exp(0.01 * i) for i in range(1, 21)]
        result = measure_coverage(
            _series(flat + drift), horizon_business_days=20, window=60
        )

        self.assertLess(result.coverage, TARGET_RANGE[0])
        self.assertFalse(result.within_target)


class MissBalanceTests(unittest.TestCase):
    def test_no_misses_reads_as_balanced(self) -> None:
        result = measure_coverage(
            _series(_alternating(400, 0.004)), horizon_business_days=20, window=60
        )

        self.assertEqual(0, result.below + result.above)
        self.assertEqual(0.5, result.miss_balance)

    def test_one_sided_misses_are_visible(self) -> None:
        """A rising series should miss above, not below."""
        flat = [1400.0] * 81
        climb = [1400.0 * math.exp(0.02 * i) for i in range(1, 21)]
        result = measure_coverage(
            _series(flat + climb), horizon_business_days=20, window=60
        )

        self.assertGreater(result.above, 0)
        self.assertEqual(0, result.below)
        self.assertEqual(0.0, result.miss_balance)


if __name__ == "__main__":
    unittest.main()
