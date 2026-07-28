import math
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.enums import (
    AvailabilityStatus,
    FinancialInstrumentKind,
    HedgeMeasureCategory,
)
from tradeflow.domain.models import HedgeMeasure
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.tools.fx_series import usd_krw_series
from tradeflow.tools.hedge_models import (
    CHAMPION_MODEL_ID,
    EwmaNormalScenarioModel,
    GarchFilteredHistoricalScenarioModel,
    HedgeModelRequest,
    HistoricalScenarioModel,
    RollingNormalScenarioModel,
    default_hedge_model_registry,
    minimum_variance_hedge_ratio,
)
from tradeflow.tools.hedge_model_validation import (
    HedgeModelPromotionPolicy,
    StressPeriod,
    assess_model_promotion,
    compare_registered_models,
    walk_forward_validate,
)


ROOT = Path(__file__).resolve().parents[2]


def series(
    count: int = 500,
    *,
    volatility: float = 0.006,
) -> tuple[tuple[date, Decimal], ...]:
    start = date(2024, 1, 1)
    rates = [1400.0]
    for index in range(1, count):
        wave = math.sin(index * 0.37) + 0.35 * math.sin(index * 0.11)
        rates.append(rates[-1] * math.exp(volatility * wave))
    return tuple(
        (
            start + timedelta(days=index),
            Decimal(repr(rate)),
        )
        for index, rate in enumerate(rates)
    )


def measure(rate: Decimal | None = None) -> HedgeMeasure:
    return HedgeMeasure(
        "QUOTE-1",
        HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
        FinancialInstrumentKind.FORWARD,
        AvailabilityStatus.AVAILABLE,
        contract_rate=rate or Decimal("1400"),
        cost_rate=Decimal("0.001"),
        source_ids=("USER_QUOTE:BANK:Q1",),
    )


def request(
    observations: tuple[tuple[date, Decimal], ...] | None = None,
) -> HedgeModelRequest:
    observations = observations or series()
    return HedgeModelRequest(
        observations=observations,
        measure=measure(observations[-1][1]),
        net_exposure=Decimal("100000"),
        baseline_profit=Decimal("2000000"),
        profit_floor=Decimal("1000000"),
        horizon_business_days=20,
        confidence_level=0.95,
        window=120,
    )


class HedgeModelRegistryTests(unittest.TestCase):
    def test_registry_has_one_explicit_champion_and_four_challengers(self) -> None:
        registry = default_hedge_model_registry()

        self.assertEqual(CHAMPION_MODEL_ID, registry.champion.model_id)
        self.assertEqual(
            {
                "rolling_normal_profit_floor",
                "historical_profit_floor",
                "ewma_profit_floor",
                "garch_fhs_profit_floor",
                "historical_cvar",
            },
            set(registry.models),
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            registry.register(registry.champion)
        with self.assertRaisesRegex(KeyError, "unknown"):
            registry.get("missing")

    def test_every_registered_model_returns_bounded_auditable_decision(self) -> None:
        decisions = default_hedge_model_registry().evaluate_all(request())

        self.assertEqual(5, len(decisions))
        for model_id, decision in decisions.items():
            with self.subTest(model=model_id):
                self.assertEqual(model_id, decision.model_id)
                self.assertGreaterEqual(decision.recommended_ratio, 0)
                self.assertLessEqual(decision.recommended_ratio, 1)
                self.assertGreater(decision.scenario_count, 0)
                self.assertGreater(decision.adverse_rate, 0)
                self.assertTrue(decision.parameters)


class ScenarioModelTests(unittest.TestCase):
    def test_historical_model_uses_only_realized_horizon_moves(self) -> None:
        model = HistoricalScenarioModel()
        forecast = model.forecast(request())

        self.assertEqual("historical", forecast.family)
        self.assertEqual(120, len(forecast.scenarios))
        self.assertEqual(
            "overlapping_horizon_returns",
            forecast.parameters["resampling"],
        )

    def test_ewma_reacts_more_to_recent_shocks_than_rolling_window(self) -> None:
        calm = list(series(250, volatility=0.001))
        rate = float(calm[-1][1])
        for index in range(12):
            rate *= math.exp(0.035 * (1 if index % 2 else -1))
            calm.append(
                (
                    calm[-1][0] + timedelta(days=1),
                    Decimal(repr(rate)),
                )
            )
        shocked = request(tuple(calm))
        rolling = RollingNormalScenarioModel().forecast(shocked)
        ewma = EwmaNormalScenarioModel().forecast(shocked)

        rolling_width = rolling.upper_rate - rolling.lower_rate
        ewma_width = ewma.upper_rate - ewma.lower_rate
        self.assertGreater(ewma_width, rolling_width)

    def test_garch_fhs_preserves_empirical_innovations_and_parameters(self) -> None:
        forecast = GarchFilteredHistoricalScenarioModel().forecast(request())

        self.assertEqual("garch_filtered_historical", forecast.family)
        self.assertGreater(forecast.parameters["alpha"], 0)
        self.assertGreater(forecast.parameters["beta"], 0)
        self.assertLess(
            forecast.parameters["alpha"] + forecast.parameters["beta"],
            1,
        )
        self.assertEqual(
            "empirical_standardized_residuals",
            forecast.parameters["innovation_distribution"],
        )

    def test_minimum_variance_ratio_uses_paired_forward_history(self) -> None:
        spot = [Decimal("100")]
        forward = [Decimal("100")]
        for index in range(1, 81):
            spot_return = 0.002 * math.sin(index * 0.31)
            forward_return = spot_return * 2
            spot.append(spot[-1] * Decimal(repr(math.exp(spot_return))))
            forward.append(
                forward[-1] * Decimal(repr(math.exp(forward_return)))
            )

        estimate = minimum_variance_hedge_ratio(spot, forward, window=60)

        self.assertAlmostEqual(0.5, float(estimate.ratio), places=10)
        self.assertEqual(60, estimate.observation_count)
        self.assertFalse(estimate.clipped)

    def test_minimum_variance_ratio_refuses_unpaired_or_constant_history(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "aligned"):
            minimum_variance_hedge_ratio(
                [Decimal("100")] * 61,
                [Decimal("100")] * 60,
                window=60,
            )
        with self.assertRaisesRegex(ValueError, "variance"):
            minimum_variance_hedge_ratio(
                [Decimal(index) for index in range(100, 161)],
                [Decimal("100")] * 61,
                window=60,
            )


class WalkForwardValidationTests(unittest.TestCase):
    def test_walk_forward_has_no_lookahead_and_returns_economic_metrics(self) -> None:
        model = default_hedge_model_registry().champion
        result = walk_forward_validate(
            model,
            series(),
            net_exposure=Decimal("100000"),
            baseline_profit=Decimal("2000000"),
            profit_floor=Decimal("1000000"),
            horizon_business_days=20,
            window=120,
            step=7,
            cost_rate=Decimal("0.001"),
            stress_periods=(
                StressPeriod(
                    "late_sample",
                    date(2025, 1, 1),
                    date(2026, 1, 1),
                ),
            ),
        )

        self.assertGreater(result.tested, 40)
        self.assertEqual(0, result.failed)
        self.assertTrue(
            all(point.origin_date < point.target_date for point in result.points)
        )
        self.assertGreaterEqual(result.adverse_breach_rate, 0)
        self.assertLessEqual(result.adverse_breach_rate, 1)
        self.assertGreaterEqual(result.mean_ratio, 0)
        self.assertGreaterEqual(result.ratio_turnover, 0)
        self.assertIn("late_sample", result.stress_metrics)

    def test_proxy_quotes_block_promotion_even_when_metrics_improve(self) -> None:
        registry = default_hedge_model_registry()
        champion = walk_forward_validate(
            registry.champion,
            series(),
            net_exposure=Decimal("100000"),
            baseline_profit=Decimal("2000000"),
            profit_floor=Decimal("1000000"),
            horizon_business_days=20,
            window=120,
            step=3,
        )
        better = replace(
            champion,
            model_id="challenger",
            expected_shortfall=champion.expected_shortfall
            * Decimal("0.5"),
            mean_quantile_loss=champion.mean_quantile_loss
            * Decimal("0.5"),
        )
        assessment = assess_model_promotion(
            champion,
            better,
            HedgeModelPromotionPolicy(minimum_origins=50),
        )

        self.assertFalse(assessment.eligible)
        self.assertTrue(
            any("forward quotes" in item for item in assessment.blockers)
        )

    def test_observed_quote_challenger_can_pass_all_numeric_gates(self) -> None:
        registry = default_hedge_model_registry()
        champion = walk_forward_validate(
            registry.champion,
            series(),
            net_exposure=Decimal("100000"),
            baseline_profit=Decimal("100000"),
            profit_floor=Decimal("1000000"),
            horizon_business_days=20,
            window=120,
            step=3,
            quote_basis="observed_forward_quote",
        )
        better = replace(
            champion,
            model_id="challenger",
            expected_shortfall=champion.expected_shortfall
            * Decimal("0.5"),
            mean_quantile_loss=champion.mean_quantile_loss
            * Decimal("0.5"),
            adverse_calibration_error=0,
        )
        assessment = assess_model_promotion(
            champion,
            better,
            HedgeModelPromotionPolicy(minimum_origins=50),
        )

        self.assertTrue(assessment.eligible, assessment.blockers)


class RealEcosModelTests(unittest.TestCase):
    def test_all_models_run_on_committed_ecos_history_without_promotion(self) -> None:
        _, payload = read_snapshot(
            ROOT / "data" / "snapshots" / "ECOS_USD_KRW" / "2026-07-27.json"
        )
        observations = usd_krw_series(payload)
        registry = default_hedge_model_registry()
        results = compare_registered_models(
            registry,
            observations,
            net_exposure=Decimal("100000"),
            baseline_profit=Decimal("50000000"),
            profit_floor=Decimal("45000000"),
            horizon_business_days=20,
            window=250,
            step=20,
            quote_basis="spot_proxy",
            stress_periods=(
                StressPeriod("pandemic", date(2020, 2, 1), date(2020, 6, 30)),
                StressPeriod("dollar_surge", date(2022, 7, 1), date(2022, 12, 31)),
            ),
        )

        self.assertEqual(set(registry.models), set(results))
        self.assertTrue(all(item.tested >= 100 for item in results.values()))
        champion = results[CHAMPION_MODEL_ID]
        for model_id, challenger in results.items():
            if model_id == CHAMPION_MODEL_ID:
                continue
            assessment = assess_model_promotion(champion, challenger)
            self.assertFalse(assessment.eligible)
            self.assertTrue(
                any("forward quotes" in item for item in assessment.blockers)
            )


if __name__ == "__main__":
    unittest.main()
