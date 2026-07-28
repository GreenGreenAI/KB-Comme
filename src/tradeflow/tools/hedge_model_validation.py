"""No-lookahead hedge-model validation and guarded promotion decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from tradeflow.domain.enums import (
    AvailabilityStatus,
    FinancialInstrumentKind,
    HedgeMeasureCategory,
)
from tradeflow.domain.models import HedgeMeasure
from tradeflow.tools.hedge_models import (
    HedgeDecisionModel,
    HedgeModelDecision,
    HedgeModelError,
    HedgeModelRegistry,
    HedgeModelRequest,
)


QuoteRateProvider = Callable[[date, int, Decimal], Decimal]


@dataclass(frozen=True)
class StressPeriod:
    name: str
    start: date
    end: date

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("stress period name is required")
        if self.end < self.start:
            raise ValueError("stress period end must not precede start")


@dataclass(frozen=True)
class WalkForwardPoint:
    origin_date: date
    target_date: date
    actual_rate: Decimal
    decision: HedgeModelDecision
    realized_profit: Decimal
    profit_floor_breached: bool
    shortfall: Decimal
    adverse_rate_breached: bool
    quantile_loss: Decimal


@dataclass(frozen=True)
class StressMetrics:
    tested: int
    floor_breach_rate: float
    expected_shortfall: Decimal
    maximum_shortfall: Decimal


@dataclass(frozen=True)
class HedgeModelBacktestResult:
    model_id: str
    model_version: str
    scenario_centering: str
    quote_basis: str
    tested: int
    failed: int
    first_origin: date
    last_origin: date
    adverse_breach_rate: float
    adverse_calibration_error: float
    floor_breach_rate: float
    mean_shortfall: Decimal
    expected_shortfall: Decimal
    maximum_shortfall: Decimal
    mean_ratio: Decimal
    ratio_turnover: Decimal
    mean_estimated_cost: Decimal
    mean_quantile_loss: Decimal
    stress_metrics: Mapping[str, StressMetrics] = field(default_factory=dict)
    points: tuple[WalkForwardPoint, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "stress_metrics",
            MappingProxyType(dict(self.stress_metrics)),
        )
        object.__setattr__(self, "points", tuple(self.points))


class WalkForwardError(ValueError):
    """The validation set cannot produce an honest out-of-sample origin."""


def _realized_profit(
    request: HedgeModelRequest,
    decision: HedgeModelDecision,
    actual_rate: Decimal,
) -> Decimal:
    ratio = decision.recommended_ratio
    spot = request.observations[-1][1]
    contract = request.measure.contract_rate
    assert contract is not None
    cost_rate = request.measure.cost_rate or Decimal("0")
    return (
        request.baseline_profit
        + request.net_exposure
        * (
            (Decimal("1") - ratio) * (actual_rate - spot)
            + ratio * (contract - spot)
        )
        - cost_rate * ratio * abs(request.net_exposure) * spot
    )


def _tail_average(
    values: Sequence[Decimal],
    confidence_level: float,
) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values, reverse=True)
    count = max(1, math.ceil((1 - confidence_level) * len(ordered)))
    return sum(ordered[:count], Decimal("0")) / count


def _stress_metrics(
    points: Sequence[WalkForwardPoint],
    confidence_level: float,
) -> StressMetrics:
    shortfalls = [point.shortfall for point in points]
    return StressMetrics(
        tested=len(points),
        floor_breach_rate=(
            sum(point.profit_floor_breached for point in points) / len(points)
            if points
            else 0
        ),
        expected_shortfall=_tail_average(shortfalls, confidence_level),
        maximum_shortfall=max(shortfalls, default=Decimal("0")),
    )


def walk_forward_validate(
    model: HedgeDecisionModel,
    observations: Sequence[tuple[date, Decimal]],
    *,
    net_exposure: Decimal,
    baseline_profit: Decimal,
    profit_floor: Decimal,
    horizon_business_days: int,
    window: int = 250,
    confidence_level: float = 0.95,
    ratio_step: Decimal = Decimal("0.01"),
    step: int = 1,
    quote_rate_provider: QuoteRateProvider | None = None,
    quote_basis: str = "spot_proxy",
    cost_rate: Decimal = Decimal("0"),
    stress_periods: tuple[StressPeriod, ...] = (),
) -> HedgeModelBacktestResult:
    """Evaluate each origin with history ending at that origin only."""
    if step < 1:
        raise WalkForwardError("step must be positive")
    if not quote_basis:
        raise WalkForwardError("quote_basis is required")
    ordered = tuple(sorted(observations, key=lambda item: item[0]))
    dates = [item[0] for item in ordered]
    if len(dates) != len(set(dates)):
        raise WalkForwardError("validation observations contain duplicate dates")
    first = window
    last = len(ordered) - horizon_business_days - 1
    if last < first:
        raise WalkForwardError(
            "history cannot supply one complete walk-forward origin"
        )

    provider = quote_rate_provider or (
        lambda _origin, _horizon, spot: spot
    )
    points: list[WalkForwardPoint] = []
    failed = 0
    for index in range(first, last + 1, step):
        history = ordered[: index + 1]
        origin_date, spot = history[-1]
        target_date, actual = ordered[index + horizon_business_days]
        contract_rate = provider(origin_date, horizon_business_days, spot)
        if contract_rate <= 0:
            raise WalkForwardError("quote provider returned a non-positive rate")
        measure = HedgeMeasure(
            measure_id=f"BACKTEST:{model.model_id}:{origin_date.isoformat()}",
            category=HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
            kind=FinancialInstrumentKind.FORWARD,
            status=AvailabilityStatus.AVAILABLE,
            contract_rate=contract_rate,
            cost_rate=cost_rate,
            source_ids=(f"BACKTEST_QUOTE:{quote_basis}",),
        )
        request = HedgeModelRequest(
            observations=history,
            measure=measure,
            net_exposure=net_exposure,
            baseline_profit=baseline_profit,
            profit_floor=profit_floor,
            horizon_business_days=horizon_business_days,
            confidence_level=confidence_level,
            window=window,
            ratio_step=ratio_step,
        )
        try:
            decision = model.analyze(request)
        except HedgeModelError:
            failed += 1
            continue
        realized = _realized_profit(request, decision, actual)
        shortfall = max(profit_floor - realized, Decimal("0"))
        if net_exposure > 0:
            adverse_breach = actual < decision.adverse_rate
            quantile_probability = 1 - confidence_level
            error = actual - decision.adverse_rate
        else:
            adverse_breach = actual > decision.adverse_rate
            quantile_probability = confidence_level
            error = actual - decision.adverse_rate
        quantile_loss = max(
            Decimal(repr(quantile_probability)) * error,
            Decimal(repr(quantile_probability - 1)) * error,
        )
        points.append(
            WalkForwardPoint(
                origin_date=origin_date,
                target_date=target_date,
                actual_rate=actual,
                decision=decision,
                realized_profit=realized,
                profit_floor_breached=shortfall > 0,
                shortfall=shortfall,
                adverse_rate_breached=adverse_breach,
                quantile_loss=quantile_loss,
            )
        )
    if not points:
        raise WalkForwardError("all model evaluations failed")

    shortfalls = [point.shortfall for point in points]
    ratios = [point.decision.recommended_ratio for point in points]
    costs = [point.decision.estimated_cost for point in points]
    losses = [point.quantile_loss for point in points]
    adverse_breach_rate = (
        sum(point.adverse_rate_breached for point in points) / len(points)
    )
    expected_adverse_rate = 1 - confidence_level
    stress = {
        period.name: _stress_metrics(
            [
                point
                for point in points
                if period.start <= point.target_date <= period.end
            ],
            confidence_level,
        )
        for period in stress_periods
    }
    return HedgeModelBacktestResult(
        model_id=model.model_id,
        model_version=model.model_version,
        scenario_centering=model.scenario_centering,
        quote_basis=quote_basis,
        tested=len(points),
        failed=failed,
        first_origin=points[0].origin_date,
        last_origin=points[-1].origin_date,
        adverse_breach_rate=adverse_breach_rate,
        adverse_calibration_error=abs(
            adverse_breach_rate - expected_adverse_rate
        ),
        floor_breach_rate=(
            sum(point.profit_floor_breached for point in points) / len(points)
        ),
        mean_shortfall=sum(shortfalls, Decimal("0")) / len(points),
        expected_shortfall=_tail_average(shortfalls, confidence_level),
        maximum_shortfall=max(shortfalls),
        mean_ratio=sum(ratios, Decimal("0")) / len(points),
        ratio_turnover=(
            sum(
                abs(ratios[index] - ratios[index - 1])
                for index in range(1, len(ratios))
            )
            / max(1, len(ratios) - 1)
        ),
        mean_estimated_cost=sum(costs, Decimal("0")) / len(points),
        mean_quantile_loss=sum(losses, Decimal("0")) / len(points),
        stress_metrics=stress,
        points=tuple(points),
    )


def compare_registered_models(
    registry: HedgeModelRegistry,
    observations: Sequence[tuple[date, Decimal]],
    **kwargs: object,
) -> Mapping[str, HedgeModelBacktestResult]:
    return MappingProxyType(
        {
            model_id: walk_forward_validate(
                model,
                observations,
                **kwargs,
            )
            for model_id, model in registry.models.items()
        }
    )


@dataclass(frozen=True)
class HedgeModelPromotionPolicy:
    minimum_origins: int = 100
    maximum_model_failures: int = 0
    maximum_calibration_error: float = 0.03
    minimum_es_improvement: float = 0.02
    minimum_quantile_loss_improvement: float = 0.01
    maximum_floor_breach_increase: float = 0
    maximum_cost_increase: float = 0.10
    maximum_turnover_increase: Decimal = Decimal("0.05")
    require_observed_forward_quotes: bool = True
    allowed_scenario_centering: tuple[str, ...] = ("zero", "not_applicable")


@dataclass(frozen=True)
class HedgeModelPromotionAssessment:
    champion_id: str
    challenger_id: str
    eligible: bool
    blockers: tuple[str, ...]


def _relative_improvement(champion: Decimal, challenger: Decimal) -> float:
    if champion == 0:
        return 0 if challenger == 0 else -math.inf
    return float((champion - challenger) / champion)


def assess_model_promotion(
    champion: HedgeModelBacktestResult,
    challenger: HedgeModelBacktestResult,
    policy: HedgeModelPromotionPolicy = HedgeModelPromotionPolicy(),
) -> HedgeModelPromotionAssessment:
    """Require calibration, economics, data quality and stability together."""
    blockers: list[str] = []
    if challenger.tested < policy.minimum_origins:
        blockers.append(
            f"tested origins {challenger.tested} < {policy.minimum_origins}"
        )
    if challenger.failed > policy.maximum_model_failures:
        blockers.append(
            f"model failures {challenger.failed} > "
            f"{policy.maximum_model_failures}"
        )
    if challenger.adverse_calibration_error > policy.maximum_calibration_error:
        blockers.append(
            "adverse quantile calibration error exceeds policy"
        )
    if (
        challenger.floor_breach_rate
        > champion.floor_breach_rate + policy.maximum_floor_breach_increase
    ):
        blockers.append("profit-floor breach rate is worse than champion")
    if (
        _relative_improvement(
            champion.expected_shortfall,
            challenger.expected_shortfall,
        )
        < policy.minimum_es_improvement
    ):
        blockers.append("expected-shortfall improvement is insufficient")
    if (
        _relative_improvement(
            champion.mean_quantile_loss,
            challenger.mean_quantile_loss,
        )
        < policy.minimum_quantile_loss_improvement
    ):
        blockers.append("quantile-loss improvement is insufficient")
    allowed_cost = champion.mean_estimated_cost * Decimal(
        repr(1 + policy.maximum_cost_increase)
    )
    if challenger.mean_estimated_cost > allowed_cost:
        blockers.append("estimated hedge cost increase exceeds policy")
    if (
        challenger.ratio_turnover
        > champion.ratio_turnover + policy.maximum_turnover_increase
    ):
        blockers.append("hedge-ratio turnover increase exceeds policy")
    if (
        policy.require_observed_forward_quotes
        and challenger.quote_basis != "observed_forward_quote"
    ):
        blockers.append(
            "observed historical forward quotes are required for promotion"
        )
    if challenger.scenario_centering not in policy.allowed_scenario_centering:
        blockers.append(
            "scenario centering is incompatible with the non-directional "
            "product policy"
        )
    if champion.tested != challenger.tested:
        blockers.append("champion and challenger were not tested on equal origins")
    return HedgeModelPromotionAssessment(
        champion_id=champion.model_id,
        challenger_id=challenger.model_id,
        eligible=not blockers,
        blockers=tuple(blockers),
    )
