"""Comparable hedge decision models and an explicit champion registry.

The models in this module never manufacture an executable quote.  Every
decision receives an already-available ``HedgeMeasure`` carrying a real
contract rate.  Models differ only in how they build adverse rate scenarios
and choose a ratio within [0, 1].
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import NormalDist
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from tradeflow.domain.models import HedgeMeasure
from tradeflow.tools.hedge import assert_all_usable
from tradeflow.tools.volatility import log_returns


CHAMPION_MODEL_ID = "rolling_normal_profit_floor"
MODEL_VERSION = "1.0"


class HedgeModelError(ValueError):
    """A model request is malformed or has too little history."""


@dataclass(frozen=True)
class HedgeModelRequest:
    observations: tuple[tuple[date, Decimal], ...]
    measure: HedgeMeasure
    net_exposure: Decimal
    baseline_profit: Decimal
    profit_floor: Decimal
    horizon_business_days: int
    confidence_level: float = 0.95
    window: int = 250
    ratio_step: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        observations = tuple(self.observations)
        if len(observations) < 3:
            raise HedgeModelError("at least three rate observations are required")
        dates = [item[0] for item in observations]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise HedgeModelError("observations must be unique and date-ordered")
        if any(rate <= 0 for _, rate in observations):
            raise HedgeModelError("rates must be positive")
        if self.net_exposure == 0:
            raise HedgeModelError("net exposure must be non-zero")
        if self.horizon_business_days < 1:
            raise HedgeModelError("horizon_business_days must be positive")
        if not 0.5 < self.confidence_level < 1:
            raise HedgeModelError("confidence_level must be between 0.5 and 1")
        if self.window < 2:
            raise HedgeModelError("window must be at least two returns")
        if not Decimal("0") < self.ratio_step <= Decimal("1"):
            raise HedgeModelError("ratio_step must sit in (0, 1]")
        assert_all_usable((self.measure,))
        if self.measure.contract_rate is None:
            raise HedgeModelError("an executable contract rate is required")
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True)
class RateForecast:
    model_id: str
    model_version: str
    family: str
    spot_rate: Decimal
    scenarios: tuple[Decimal, ...]
    lower_rate: Decimal
    median_rate: Decimal
    upper_rate: Decimal
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        scenarios = tuple(sorted(self.scenarios))
        if not scenarios or any(rate <= 0 for rate in scenarios):
            raise HedgeModelError("forecast scenarios must be positive")
        object.__setattr__(self, "scenarios", scenarios)
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )


@dataclass(frozen=True)
class HedgeModelDecision:
    model_id: str
    model_version: str
    objective: str
    recommended_ratio: Decimal
    sufficient: bool
    status: str
    adverse_rate: Decimal
    forecast_lower: Decimal
    forecast_upper: Decimal
    breach_probability: float
    expected_shortfall: Decimal
    estimated_cost: Decimal
    scenario_count: int
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.recommended_ratio <= Decimal("1"):
            raise HedgeModelError("recommended_ratio must stay in [0, 1]")
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )


class HedgeDecisionModel(Protocol):
    model_id: str
    model_version: str
    objective: str
    scenario_centering: str

    def analyze(self, request: HedgeModelRequest) -> HedgeModelDecision: ...


class RateScenarioModel(Protocol):
    model_id: str
    model_version: str
    family: str
    scenario_centering: str

    def forecast(self, request: HedgeModelRequest) -> RateForecast: ...


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise HedgeModelError("quantile requires observations")
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _normal_scenarios(
    spot: float,
    scaled_volatility: float,
    *,
    count: int = 199,
) -> tuple[Decimal, ...]:
    return tuple(
        Decimal(
            repr(
                spot
                * math.exp(
                    NormalDist().inv_cdf((index + 0.5) / count)
                    * scaled_volatility
                )
            )
        )
        for index in range(count)
    )


def _forecast(
    *,
    model_id: str,
    family: str,
    spot: Decimal,
    scenarios: Sequence[Decimal],
    confidence_level: float,
    parameters: Mapping[str, object],
) -> RateForecast:
    alpha = 1 - confidence_level
    floats = [float(item) for item in scenarios]
    return RateForecast(
        model_id=model_id,
        model_version=MODEL_VERSION,
        family=family,
        spot_rate=spot,
        scenarios=tuple(scenarios),
        lower_rate=Decimal(repr(_quantile(floats, alpha))),
        median_rate=Decimal(repr(_quantile(floats, 0.5))),
        upper_rate=Decimal(repr(_quantile(floats, confidence_level))),
        parameters=parameters,
    )


class RollingNormalScenarioModel:
    model_id = "rolling_normal"
    model_version = MODEL_VERSION
    family = "parametric_normal"
    scenario_centering = "zero"

    def forecast(self, request: HedgeModelRequest) -> RateForecast:
        returns = log_returns(request.observations)
        if len(returns) < request.window:
            raise HedgeModelError(
                f"rolling model needs {request.window} returns; "
                f"received {len(returns)}"
            )
        used = returns[-request.window :]
        daily = statistics.stdev(used)
        scaled = daily * math.sqrt(request.horizon_business_days)
        spot = request.observations[-1][1]
        return _forecast(
            model_id=self.model_id,
            family=self.family,
            spot=spot,
            scenarios=_normal_scenarios(float(spot), scaled),
            confidence_level=request.confidence_level,
            parameters={
                "window": request.window,
                "daily_volatility": daily,
                "scaled_volatility": scaled,
                "drift": 0,
            },
        )


class HistoricalScenarioModel:
    model_id = "historical_simulation"
    model_version = MODEL_VERSION
    family = "historical"
    scenario_centering = "empirical"

    def forecast(self, request: HedgeModelRequest) -> RateForecast:
        ordered = request.observations
        horizon = request.horizon_business_days
        available = len(ordered) - horizon
        count = min(request.window, available)
        if count < 20:
            raise HedgeModelError("historical simulation needs 20 horizon returns")
        start = len(ordered) - horizon - count
        horizon_returns = [
            math.log(
                float(ordered[index + horizon][1])
                / float(ordered[index][1])
            )
            for index in range(start, len(ordered) - horizon)
        ]
        spot = ordered[-1][1]
        scenarios = tuple(
            Decimal(repr(float(spot) * math.exp(value)))
            for value in horizon_returns
        )
        return _forecast(
            model_id=self.model_id,
            family=self.family,
            spot=spot,
            scenarios=scenarios,
            confidence_level=request.confidence_level,
            parameters={
                "horizon_return_count": len(horizon_returns),
                "resampling": "overlapping_horizon_returns",
                "drift": "empirical",
            },
        )


class EwmaNormalScenarioModel:
    model_id = "ewma_normal"
    model_version = MODEL_VERSION
    family = "conditional_normal"
    scenario_centering = "zero"

    def __init__(self, decay: float = 0.94) -> None:
        if not 0 < decay < 1:
            raise ValueError("EWMA decay must sit in (0, 1)")
        self.decay = decay

    def forecast(self, request: HedgeModelRequest) -> RateForecast:
        returns = log_returns(request.observations)
        if len(returns) < request.window:
            raise HedgeModelError(
                f"EWMA needs {request.window} returns; received {len(returns)}"
            )
        used = returns[-request.window :]
        variance = statistics.variance(used)
        for value in used:
            variance = self.decay * variance + (1 - self.decay) * value * value
        scaled = math.sqrt(variance * request.horizon_business_days)
        spot = request.observations[-1][1]
        return _forecast(
            model_id=self.model_id,
            family=self.family,
            spot=spot,
            scenarios=_normal_scenarios(float(spot), scaled),
            confidence_level=request.confidence_level,
            parameters={
                "window": request.window,
                "decay": self.decay,
                "conditional_variance": variance,
                "scaled_volatility": scaled,
                "drift": 0,
            },
        )


@dataclass(frozen=True)
class GarchFit:
    omega: float
    alpha: float
    beta: float
    last_variance: float
    standardized_residuals: tuple[float, ...]
    gaussian_log_likelihood: float


def _garch_fit(returns: Sequence[float]) -> GarchFit:
    if len(returns) < 40:
        raise HedgeModelError("GARCH requires at least 40 returns")
    unconditional = statistics.variance(returns)
    if unconditional <= 0:
        return GarchFit(0, 0, 0, 0, tuple(0 for _ in returns), 0)

    best: GarchFit | None = None
    for alpha in (0.03, 0.05, 0.08, 0.12, 0.16):
        for beta in (0.70, 0.78, 0.84, 0.89, 0.93):
            if alpha + beta >= 0.995:
                continue
            omega = (1 - alpha - beta) * unconditional
            variance = unconditional
            variances: list[float] = []
            residuals: list[float] = []
            likelihood = 0.0
            for value in returns:
                variances.append(variance)
                likelihood += math.log(variance) + value * value / variance
                residuals.append(value / math.sqrt(variance))
                variance = max(
                    omega + alpha * value * value + beta * variance,
                    1e-16,
                )
            fit = GarchFit(
                omega,
                alpha,
                beta,
                variance,
                tuple(residuals),
                likelihood,
            )
            if best is None or fit.gaussian_log_likelihood < best.gaussian_log_likelihood:
                best = fit
    assert best is not None
    return best


class GarchFilteredHistoricalScenarioModel:
    model_id = "garch_filtered_historical"
    model_version = MODEL_VERSION
    family = "garch_filtered_historical"
    scenario_centering = "empirical_standardized_residuals"

    def forecast(self, request: HedgeModelRequest) -> RateForecast:
        returns = log_returns(request.observations)
        if len(returns) < request.window:
            raise HedgeModelError(
                f"GARCH-FHS needs {request.window} returns; received {len(returns)}"
            )
        used = returns[-request.window :]
        fit = _garch_fit(used)
        if fit.last_variance == 0:
            cumulative_variance = 0.0
        else:
            unconditional = fit.omega / (1 - fit.alpha - fit.beta)
            next_variance = fit.last_variance
            cumulative_variance = 0.0
            persistence = fit.alpha + fit.beta
            for _ in range(request.horizon_business_days):
                cumulative_variance += max(next_variance, 0)
                next_variance = (
                    unconditional
                    + persistence * (next_variance - unconditional)
                )
        scale = math.sqrt(cumulative_variance)
        spot = request.observations[-1][1]
        residuals = fit.standardized_residuals[-min(250, len(used)) :]
        scenarios = tuple(
            Decimal(repr(float(spot) * math.exp(residual * scale)))
            for residual in residuals
        )
        return _forecast(
            model_id=self.model_id,
            family=self.family,
            spot=spot,
            scenarios=scenarios,
            confidence_level=request.confidence_level,
            parameters={
                "window": request.window,
                "omega": fit.omega,
                "alpha": fit.alpha,
                "beta": fit.beta,
                "forecast_variance": cumulative_variance,
                "innovation_distribution": "empirical_standardized_residuals",
            },
        )


def _profit(
    request: HedgeModelRequest,
    *,
    rate: Decimal,
    ratio: Decimal,
) -> Decimal:
    exposure = request.net_exposure
    spot = request.observations[-1][1]
    contract = request.measure.contract_rate
    assert contract is not None
    cost_rate = request.measure.cost_rate or Decimal("0")
    return (
        request.baseline_profit
        + exposure
        * (
            (Decimal("1") - ratio) * (rate - spot)
            + ratio * (contract - spot)
        )
        - cost_rate * ratio * abs(exposure) * spot
    )


def _loss_metrics(
    request: HedgeModelRequest,
    forecast: RateForecast,
    ratio: Decimal,
) -> tuple[float, Decimal]:
    shortfalls = sorted(
        (
            max(
                request.profit_floor
                - _profit(request, rate=rate, ratio=ratio),
                Decimal("0"),
            )
            for rate in forecast.scenarios
        ),
        reverse=True,
    )
    breaches = sum(value > 0 for value in shortfalls)
    tail_count = max(
        1,
        math.ceil((1 - request.confidence_level) * len(shortfalls)),
    )
    expected_shortfall = sum(shortfalls[:tail_count], Decimal("0")) / tail_count
    return breaches / len(shortfalls), expected_shortfall


def _estimated_cost(request: HedgeModelRequest, ratio: Decimal) -> Decimal:
    return (
        (request.measure.cost_rate or Decimal("0"))
        * ratio
        * abs(request.net_exposure)
        * request.observations[-1][1]
    )


class QuantileProfitFloorModel:
    objective = "minimum_ratio_subject_to_adverse_profit_floor"
    model_version = MODEL_VERSION

    def __init__(
        self,
        model_id: str,
        scenario_model: RateScenarioModel,
    ) -> None:
        self.model_id = model_id
        self.scenario_model = scenario_model
        self.scenario_centering = scenario_model.scenario_centering

    def analyze(self, request: HedgeModelRequest) -> HedgeModelDecision:
        forecast = self.scenario_model.forecast(request)
        adverse = (
            forecast.lower_rate
            if request.net_exposure > 0
            else forecast.upper_rate
        )
        unhedged = _profit(request, rate=adverse, ratio=Decimal("0"))
        fully_hedged = _profit(request, rate=adverse, ratio=Decimal("1"))
        slope = fully_hedged - unhedged
        if unhedged >= request.profit_floor:
            ratio = Decimal("0")
            sufficient = True
        elif slope > 0:
            ratio = (request.profit_floor - unhedged) / slope
            sufficient = ratio <= 1
            ratio = min(max(ratio, Decimal("0")), Decimal("1"))
        else:
            ratio = Decimal("0")
            sufficient = False
        breach_probability, expected_shortfall = _loss_metrics(
            request,
            forecast,
            ratio,
        )
        return HedgeModelDecision(
            model_id=self.model_id,
            model_version=self.model_version,
            objective=self.objective,
            recommended_ratio=ratio,
            sufficient=sufficient,
            status="ok" if sufficient else "hedge_insufficient",
            adverse_rate=adverse,
            forecast_lower=forecast.lower_rate,
            forecast_upper=forecast.upper_rate,
            breach_probability=breach_probability,
            expected_shortfall=expected_shortfall,
            estimated_cost=_estimated_cost(request, ratio),
            scenario_count=len(forecast.scenarios),
            parameters={
                "scenario_model": forecast.model_id,
                "scenario_centering": self.scenario_centering,
                **dict(forecast.parameters),
            },
        )


class HistoricalCvarModel:
    model_id = "historical_cvar"
    model_version = MODEL_VERSION
    objective = "minimum_expected_shortfall_then_minimum_ratio"
    scenario_centering = "empirical"

    def __init__(self) -> None:
        self.scenario_model = HistoricalScenarioModel()

    def analyze(self, request: HedgeModelRequest) -> HedgeModelDecision:
        forecast = self.scenario_model.forecast(request)
        steps = int(Decimal("1") / request.ratio_step)
        ratios = [
            min(request.ratio_step * index, Decimal("1"))
            for index in range(steps + 1)
        ]
        if ratios[-1] != Decimal("1"):
            ratios.append(Decimal("1"))
        scored = []
        for ratio in ratios:
            breach_probability, expected_shortfall = _loss_metrics(
                request,
                forecast,
                ratio,
            )
            scored.append(
                (
                    expected_shortfall,
                    ratio,
                    breach_probability,
                )
            )
        expected_shortfall, ratio, breach_probability = min(
            scored,
            key=lambda item: (item[0], item[1]),
        )
        sufficient = expected_shortfall == 0
        adverse = (
            forecast.lower_rate
            if request.net_exposure > 0
            else forecast.upper_rate
        )
        return HedgeModelDecision(
            model_id=self.model_id,
            model_version=self.model_version,
            objective=self.objective,
            recommended_ratio=ratio,
            sufficient=sufficient,
            status="ok" if sufficient else "tail_loss_remains",
            adverse_rate=adverse,
            forecast_lower=forecast.lower_rate,
            forecast_upper=forecast.upper_rate,
            breach_probability=breach_probability,
            expected_shortfall=expected_shortfall,
            estimated_cost=_estimated_cost(request, ratio),
            scenario_count=len(forecast.scenarios),
            parameters={
                "scenario_model": forecast.model_id,
                "scenario_centering": self.scenario_centering,
                "ratio_step": str(request.ratio_step),
                "tail_probability": 1 - request.confidence_level,
            },
        )


class HedgeModelRegistry:
    """Explicit champion/challenger selection with no implicit fallback."""

    def __init__(self) -> None:
        self._models: dict[str, HedgeDecisionModel] = {}
        self._champion_id: str | None = None

    def register(
        self,
        model: HedgeDecisionModel,
        *,
        champion: bool = False,
    ) -> None:
        if not model.model_id:
            raise ValueError("model_id is required")
        if model.model_id in self._models:
            raise ValueError(f"duplicate hedge model_id: {model.model_id}")
        if champion and self._champion_id is not None:
            raise ValueError("a hedge model champion is already registered")
        self._models[model.model_id] = model
        if champion:
            self._champion_id = model.model_id

    @property
    def champion(self) -> HedgeDecisionModel:
        if self._champion_id is None:
            raise ValueError("no hedge model champion is registered")
        return self._models[self._champion_id]

    @property
    def models(self) -> Mapping[str, HedgeDecisionModel]:
        return MappingProxyType(self._models)

    def get(self, model_id: str) -> HedgeDecisionModel:
        try:
            return self._models[model_id]
        except KeyError:
            raise KeyError(f"unknown hedge model_id: {model_id}") from None

    def evaluate_all(
        self,
        request: HedgeModelRequest,
    ) -> Mapping[str, HedgeModelDecision]:
        return MappingProxyType(
            {
                model_id: model.analyze(request)
                for model_id, model in self._models.items()
            }
        )


@dataclass(frozen=True)
class MinimumVarianceHedgeEstimate:
    ratio: Decimal
    covariance: Decimal
    forward_variance: Decimal
    observation_count: int
    clipped: bool


def minimum_variance_hedge_ratio(
    spot_rates: Sequence[Decimal],
    forward_rates: Sequence[Decimal],
    *,
    window: int = 250,
) -> MinimumVarianceHedgeEstimate:
    """Estimate Ederington's covariance/variance hedge ratio.

    This is deliberately not registered as an operational model until paired
    historical forward quotes exist.  A spot-only approximation is refused.
    """
    if len(spot_rates) != len(forward_rates):
        raise HedgeModelError("spot and forward histories must be aligned")
    if len(spot_rates) < window + 1:
        raise HedgeModelError(
            f"minimum-variance model needs {window + 1} paired rates"
        )
    if any(value <= 0 for value in (*spot_rates, *forward_rates)):
        raise HedgeModelError("paired spot and forward rates must be positive")
    spot_returns = [
        math.log(float(spot_rates[index]) / float(spot_rates[index - 1]))
        for index in range(len(spot_rates) - window, len(spot_rates))
    ]
    forward_returns = [
        math.log(float(forward_rates[index]) / float(forward_rates[index - 1]))
        for index in range(len(forward_rates) - window, len(forward_rates))
    ]
    covariance = statistics.covariance(spot_returns, forward_returns)
    variance = statistics.variance(forward_returns)
    if variance <= 0:
        raise HedgeModelError("forward return variance must be positive")
    raw = covariance / variance
    bounded = min(max(raw, 0.0), 1.0)
    return MinimumVarianceHedgeEstimate(
        ratio=Decimal(repr(bounded)),
        covariance=Decimal(repr(covariance)),
        forward_variance=Decimal(repr(variance)),
        observation_count=window,
        clipped=bounded != raw,
    )


def default_hedge_model_registry() -> HedgeModelRegistry:
    registry = HedgeModelRegistry()
    registry.register(
        QuantileProfitFloorModel(
            CHAMPION_MODEL_ID,
            RollingNormalScenarioModel(),
        ),
        champion=True,
    )
    registry.register(
        QuantileProfitFloorModel(
            "historical_profit_floor",
            HistoricalScenarioModel(),
        )
    )
    registry.register(
        QuantileProfitFloorModel(
            "ewma_profit_floor",
            EwmaNormalScenarioModel(),
        )
    )
    registry.register(
        QuantileProfitFloorModel(
            "garch_fhs_profit_floor",
            GarchFilteredHistoricalScenarioModel(),
        )
    )
    registry.register(HistoricalCvarModel())
    return registry
