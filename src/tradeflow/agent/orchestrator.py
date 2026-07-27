"""Deciding which workers to run, and surviving the ones that fail.

§4.2[2] keeps this rule-based until all five workers exist; the LLM takes over
the routing decision only once there is something to route. What it does own
today is failure isolation (§9.3): a worker that fails must not take the answer
down with it, and must not be papered over either — the gap is reported as
missing information rather than filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from tradeflow.contracts.decision_packet import DecisionPacket
from tradeflow.contracts.response import project_cashflow_analysis
from tradeflow.domain.enums import Freshness
from tradeflow.domain.models import HedgeMeasure, TradeProgram
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.knowledge.facts import FactAssembler, FactCatalog
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline
from tradeflow.tools.exposure import analyze_exposure
from tradeflow.tools.fx_series import usd_krw_series
from tradeflow.tools.hedge import review_measures, usable_measures
from tradeflow.tools.hedge_ratio import HedgeAnalysis, analyze_hedge
from tradeflow.tools.volatility import ScenarioBand, require_fresh, scenario_band

FX_SOURCE = "ECOS_USD_KRW"

# A daily reference rate more than four days old has usually missed a business
# day, so a band built on it would understate how much has already moved.
FX_FRESHNESS = FreshnessPolicy(max_observation_age=timedelta(days=4))

DEFAULT_HORIZON_DAYS = 60
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class WorkerReport:
    """What each worker produced, or why it could not."""

    completed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def missing_information(self) -> tuple[str, ...]:
        return tuple(
            f"{name}: {reason}"
            for name, reason in (*self.failed.items(), *self.skipped.items())
        )


def _isolated(report: WorkerReport, name: str, run: Callable[[], Any]) -> Any | None:
    """Run one worker, recording a failure instead of propagating it (§9.3)."""
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 — any worker failure must be survivable
        report.failed[name] = f"{type(exc).__name__}: {exc}"
        return None


@dataclass(frozen=True)
class Analysis:
    """Everything the workers produced for one program."""

    program: TradeProgram
    cashflow: dict[str, Any]
    band: ScenarioBand | None
    adverse_cashflow_change: Decimal | None
    adverse_cashflow_amount: Decimal | None
    adverse_cashflow_direction: str | None
    hedge: HedgeAnalysis | None
    snapshot: SnapshotRef | None
    decision_packet: DecisionPacket | None
    report: WorkerReport
    required_inputs: tuple[str, ...]
    review_reasons: tuple[str, ...]

    @property
    def review_required(self) -> bool:
        return bool(self.review_reasons)


def _latest_snapshot(root: Path | str, source_id: str) -> Path:
    """Newest snapshot for a source.

    Versions are the observation date, so filename order is observation order
    and only the chosen file has to be read. PR #4 introduces a shared helper
    that verifies every candidate instead; switch to it once that lands.
    """
    candidates = sorted((Path(root) / source_id).glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"no snapshot stored for {source_id}")
    return candidates[-1]


def _business_days_until(target, as_of) -> int:
    """Working days between two dates, weekends removed.

    Korean public holidays are not modelled: the horizon would be slightly long
    rather than short, which widens the band rather than narrowing it.
    """
    days = 0
    current = as_of
    while current < target:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return max(days, 1)


@lru_cache(maxsize=1)
def _default_knowledge_pipeline() -> TradeFlowPipeline:
    """Load the shared Role A rulepacks once for the web process."""
    knowledge_root = REPO_ROOT / "knowledge"
    knowledge = KnowledgeRepository.from_json_files(
        knowledge_root / "source_registry.json",
        (
            knowledge_root / "rulepacks" / "ksure_mvp_candidates.json",
            knowledge_root / "rulepacks" / "fx_compliance_mvp.json",
        ),
    )
    return TradeFlowPipeline(
        knowledge,
        fact_assembler=FactAssembler(
            FactCatalog.from_json(knowledge_root / "fact_catalog.json")
        ),
    )


def analyze(
    program: TradeProgram,
    *,
    snapshot_root: Path | str,
    baseline_profit: Decimal | None = None,
    profit_floor: Decimal | None = None,
    hedge_measures: tuple[HedgeMeasure, ...] = (),
    knowledge_pipeline: TradeFlowPipeline | None = None,
    as_of: datetime | None = None,
) -> Analysis:
    """Run the workers this program calls for, keeping failures contained."""
    report = WorkerReport()
    review: list[str] = []

    exposures = analyze_exposure(program)
    report.completed.append("exposure")
    cashflow = project_cashflow_analysis(exposures)

    pipeline = knowledge_pipeline or _default_knowledge_pipeline()
    decision_packet = _isolated(
        report,
        "knowledge",
        lambda: pipeline.analyze_case_packet(
            program,
            assertions_by_case={case.case_id: () for case in program.cases},
            evidence=(),
        ),
    )
    if decision_packet is not None:
        report.completed.extend(("support", "compliance"))
        review.extend(decision_packet.review_reasons)
    else:
        review.append(
            "지원제도와 신고의무 규칙을 실행하지 못해 전문가 검토가 필요합니다"
        )

    horizon = max(
        (
            _business_days_until(case.expected_payment_date, program.as_of)
            for case in program.cases
        ),
        default=DEFAULT_HORIZON_DAYS,
    )

    band: ScenarioBand | None = None
    snapshot: SnapshotRef | None = None

    def _market() -> ScenarioBand:
        nonlocal snapshot
        path = _latest_snapshot(snapshot_root, FX_SOURCE)
        ref, payload = read_snapshot(path)
        snapshot = ref
        require_fresh(ref, FX_FRESHNESS, as_of or datetime.now(ref.observed_at.tzinfo))
        return scenario_band(usd_krw_series(payload), horizon_business_days=horizon)

    band = _isolated(report, "market_scenario", _market)
    if band is not None:
        report.completed.append("market_scenario")
    else:
        review.append("환율 시나리오를 산출하지 못해 손익 평가가 빠졌습니다")

    net_exposure = exposures[0].trade_net_exposure if exposures else Decimal("0")
    adverse_cashflow_change: Decimal | None = None
    adverse_cashflow_amount: Decimal | None = None
    adverse_cashflow_direction: str | None = None
    if band is not None and net_exposure != 0:
        adverse_rate = band.lower if net_exposure > 0 else band.upper
        adverse_cashflow_change = (
            net_exposure * (adverse_rate - band.spot_rate)
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        adverse_cashflow_amount = abs(adverse_cashflow_change)
        adverse_cashflow_direction = (
            "decrease" if adverse_cashflow_change < 0 else "increase"
        )

    hedge: HedgeAnalysis | None = None
    required_inputs: list[str] = []
    available_measures = usable_measures(hedge_measures)
    unsettled_measures = review_measures(hedge_measures)
    if unsettled_measures:
        review.append(
            "헤지 수단의 이용 가능성이 확정되지 않아 손익 계산에서 제외했습니다"
        )

    if net_exposure == 0:
        report.skipped["hedge"] = "순노출이 0이어서 헤지가 필요하지 않습니다"
    elif band is None:
        report.skipped["hedge"] = "환율 시나리오가 없어 헤지비율을 계산할 수 없습니다"
    elif not available_measures:
        report.skipped["hedge"] = (
            "검증된 이용 가능 헤지 수단과 가격 정보가 없어 계산하지 않았습니다"
        )
    elif baseline_profit is None:
        report.skipped["hedge"] = "기준 영업이익을 입력하면 헤지비율을 계산할 수 있습니다"
        required_inputs.append("baseline_profit")
    elif profit_floor is None:
        report.skipped["hedge"] = "목표 손익 하한을 입력하면 헤지비율을 계산할 수 있습니다"
        required_inputs.append("profit_floor")
    else:
        measure = available_measures[0]
        hedge = _isolated(
            report,
            "hedge",
            lambda: analyze_hedge(
                measure,
                net_exposure=net_exposure,
                spot_rate=band.spot_rate,
                baseline_profit=baseline_profit,
                scaled_volatility=band.scaled_volatility,
                profit_floor=profit_floor,
            ),
        )
        if hedge is not None:
            report.completed.append("hedge")
            if not hedge.sufficient:
                review.append(
                    "목표 손실한도를 헤지만으로 달성할 수 없어 전문가 검토가 필요합니다"
                )

    if snapshot is not None and FX_FRESHNESS.evaluate(
        snapshot, as_of or datetime.now(snapshot.observed_at.tzinfo)
    ) is not Freshness.FRESH:
        review.append("환율 스냅샷이 최신성 기준을 넘겨 판단 근거에서 제외되었습니다")

    return Analysis(
        program=program,
        cashflow=cashflow,
        band=band,
        adverse_cashflow_change=adverse_cashflow_change,
        adverse_cashflow_amount=adverse_cashflow_amount,
        adverse_cashflow_direction=adverse_cashflow_direction,
        hedge=hedge,
        snapshot=snapshot,
        decision_packet=decision_packet,
        report=report,
        required_inputs=tuple(required_inputs),
        review_reasons=tuple(dict.fromkeys(review)),
    )
