import math
import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef
from tradeflow.tools.volatility import (
    BUSINESS_DAYS_PER_YEAR,
    InsufficientObservationsError,
    StaleSnapshotError,
    estimate_volatility,
    log_returns,
    require_fresh,
    scenario_band,
    z_for,
)


def _flat(days: int, rate: str = "1400.0") -> list[tuple[date, Decimal]]:
    start = date(2026, 1, 5)
    return [(start + timedelta(days=i), Decimal(rate)) for i in range(days)]


def _geometric(days: int, step: float) -> list[tuple[date, Decimal]]:
    """A series whose log returns are all exactly `step`."""
    start = date(2026, 1, 5)
    return [
        (start + timedelta(days=i), Decimal(repr(1400.0 * math.exp(step * i))))
        for i in range(days)
    ]


def _alternating(days: int, step: float) -> list[tuple[date, Decimal]]:
    """A series that moves by ±step each day, so volatility is non-zero."""
    start = date(2026, 1, 5)
    rates = [1400.0]
    for i in range(days - 1):
        rates.append(rates[-1] * math.exp(step * (1 if i % 2 else -1)))
    return [
        (start + timedelta(days=i), Decimal(repr(round(rate, 6))))
        for i, rate in enumerate(rates)
    ]


class LogReturnTests(unittest.TestCase):
    def test_returns_are_one_shorter_than_the_series(self) -> None:
        self.assertEqual(9, len(log_returns(_flat(10))))

    def test_flat_series_has_zero_returns(self) -> None:
        self.assertEqual([0.0] * 4, log_returns(_flat(5)))

    def test_constant_growth_gives_constant_returns(self) -> None:
        returns = log_returns(_geometric(5, 0.01))

        for value in returns:
            self.assertAlmostEqual(0.01, value, places=9)

    def test_series_is_ordered_before_differencing(self) -> None:
        ordered = _geometric(4, 0.01)
        shuffled = [ordered[2], ordered[0], ordered[3], ordered[1]]

        self.assertEqual(log_returns(ordered), log_returns(shuffled))

    def test_duplicate_dates_are_rejected(self) -> None:
        series = _flat(3)
        with self.assertRaises(ValueError):
            log_returns([*series, series[0]])

    def test_non_positive_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            log_returns([(date(2026, 1, 5), Decimal("0"))])


class VolatilityEstimateTests(unittest.TestCase):
    def test_constant_growth_has_zero_volatility(self) -> None:
        estimate = estimate_volatility(_geometric(61, 0.002), window=60)

        self.assertAlmostEqual(0.0, estimate.daily, places=12)

    def test_annualization_uses_the_business_day_convention(self) -> None:
        estimate = estimate_volatility(_alternating(61, 0.004), window=60)

        self.assertGreater(estimate.daily, 0.0)
        self.assertAlmostEqual(
            estimate.daily * math.sqrt(BUSINESS_DAYS_PER_YEAR),
            estimate.annualized,
            places=12,
        )

    def test_only_the_requested_window_is_used(self) -> None:
        quiet = _geometric(200, 0.0)
        estimate = estimate_volatility(quiet, window=60)

        self.assertEqual(60, estimate.window)
        self.assertEqual(quiet[-61][0], estimate.first_observed)
        self.assertEqual(quiet[-1][0], estimate.last_observed)

    def test_short_series_is_refused_not_silently_shortened(self) -> None:
        with self.assertRaises(InsufficientObservationsError) as caught:
            estimate_volatility(_flat(40), window=60)

        self.assertIn("60", str(caught.exception))
        self.assertIn("40", str(caught.exception))

    def test_window_needs_at_least_two_returns(self) -> None:
        with self.assertRaises(ValueError):
            estimate_volatility(_flat(10), window=1)


class ZScoreTests(unittest.TestCase):
    def test_reproduces_the_values_the_spec_tabulates(self) -> None:
        self.assertAlmostEqual(1.645, z_for(0.90), places=3)
        self.assertAlmostEqual(1.96, z_for(0.95), places=2)

    def test_wider_confidence_widens_the_score(self) -> None:
        self.assertLess(z_for(0.90), z_for(0.99))

    def test_confidence_outside_the_unit_interval_is_rejected(self) -> None:
        for level in (0.0, 1.0, -0.1, 1.5):
            with self.subTest(level=level), self.assertRaises(ValueError):
                z_for(level)


class ScenarioBandTests(unittest.TestCase):
    def setUp(self) -> None:
        # A series with a known, non-zero daily volatility.
        start = date(2026, 1, 5)
        rates = [1400.0]
        for i in range(80):
            rates.append(rates[-1] * math.exp(0.004 * (1 if i % 2 else -1)))
        self.series = [
            (start + timedelta(days=i), Decimal(repr(round(rate, 4))))
            for i, rate in enumerate(rates)
        ]

    def test_band_is_centred_on_the_latest_rate(self) -> None:
        band = scenario_band(self.series, horizon_business_days=60)

        self.assertEqual(self.series[-1][1], band.spot_rate)
        spot = float(band.spot_rate)
        self.assertAlmostEqual(
            spot / float(band.lower), float(band.upper) / spot, places=4
        )

    def test_no_drift_means_the_band_straddles_the_spot(self) -> None:
        band = scenario_band(self.series, horizon_business_days=60)

        self.assertLess(band.lower, band.spot_rate)
        self.assertGreater(band.upper, band.spot_rate)

    def test_longer_horizon_widens_the_band(self) -> None:
        near = scenario_band(self.series, horizon_business_days=20)
        far = scenario_band(self.series, horizon_business_days=80)

        self.assertLess(far.lower, near.lower)
        self.assertGreater(far.upper, near.upper)

    def test_horizon_scales_with_the_square_root_of_time(self) -> None:
        one = scenario_band(self.series, horizon_business_days=25)
        four = scenario_band(self.series, horizon_business_days=100)

        self.assertAlmostEqual(
            2.0, four.scaled_volatility / one.scaled_volatility, places=9
        )

    def test_higher_confidence_widens_the_band(self) -> None:
        ninety = scenario_band(self.series, horizon_business_days=60)
        ninety_five = scenario_band(
            self.series, horizon_business_days=60, confidence_level=0.95
        )

        self.assertLess(ninety_five.lower, ninety.lower)
        self.assertGreater(ninety_five.upper, ninety.upper)

    def test_result_carries_the_basis_needed_to_read_it(self) -> None:
        band = scenario_band(self.series, horizon_business_days=60)

        self.assertEqual("KRW per USD", band.unit)
        self.assertEqual("ROUND_HALF_UP", band.rounding)
        self.assertEqual(60, band.horizon_business_days)
        self.assertEqual(0.90, band.confidence_level)
        self.assertEqual(60, band.volatility.window)

    def test_zero_horizon_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            scenario_band(self.series, horizon_business_days=0)

    def test_flat_series_collapses_the_band_onto_the_spot(self) -> None:
        band = scenario_band(_flat(61), horizon_business_days=60)

        self.assertEqual(band.lower, band.upper)
        self.assertEqual(Decimal("1400.00"), band.lower)


class FreshnessGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ref = SnapshotRef(
            "ECOS_USD_KRW",
            "2026-07-24",
            datetime(2026, 7, 24, tzinfo=UTC),
            datetime(2026, 7, 24, 1, tzinfo=UTC),
            "sha256:test",
        )
        self.policy = FreshnessPolicy(max_observation_age=timedelta(days=5))

    def test_fresh_snapshot_passes(self) -> None:
        require_fresh(self.ref, self.policy, datetime(2026, 7, 26, tzinfo=UTC))

    def test_stale_snapshot_stops_the_worker(self) -> None:
        with self.assertRaises(StaleSnapshotError) as caught:
            require_fresh(self.ref, self.policy, datetime(2026, 8, 20, tzinfo=UTC))

        self.assertIn("ECOS_USD_KRW", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
