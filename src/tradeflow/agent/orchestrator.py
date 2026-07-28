"""Deciding which workers to run, and surviving the ones that fail.

§4.2[2] keeps this rule-based until all five workers exist; the LLM takes over
the routing decision only once there is something to route. What it does own
today is failure isolation (§9.3): a worker that fails must not take the answer
down with it, and must not be papered over either — the gap is reported as
missing information rather than filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

from tradeflow.contracts.decision_packet import DecisionPacket
from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.contracts.response import project_cashflow_analysis
from tradeflow.domain.enums import EvidenceRole, Freshness
from tradeflow.domain.models import HedgeMeasure, TradeProgram
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef
from tradeflow.domain.snapshot_file import latest_snapshot_path, read_snapshot
from tradeflow.knowledge.facts import FactAssembler, FactAssertion, FactCatalog
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.agent.routing import (
    COMPLIANCE,
    derive_structure,
    EXPOSURE,
    HEDGE,
    MARKET,
    SUPPORT,
    ExecutionPlan,
    plan_execution,
)
from tradeflow.runtime.pipeline import TradeFlowPipeline
from tradeflow.runtime.provenance import (
    CalculationVersions,
    InputFile,
    canonical_business_inputs,
    fingerprint_knowledge,
    snapshot_versions,
)
from tradeflow.tools.exposure import analyze_exposure
from tradeflow.tools.fx_series import usd_krw_series
from tradeflow.tools.hedge import review_measures, usable_measures
from tradeflow.tools.hedge_ratio import HedgeAnalysis, analyze_hedge
from tradeflow.tools.intent import read_intent
from tradeflow.tools.source_freshness import load_source_verification
from tradeflow.tools.volatility import ScenarioBand, require_fresh, scenario_band

FX_SOURCE = "ECOS_USD_KRW"

# Which tool versions produced the figures. Kept here rather than in
# response.py because the orchestrator records it and response.py reads
# it back out of the analysis.
FORMULA_VERSION = "exposure.v1+scenario.v1+hedge.v1"

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
    versions: CalculationVersions
    plan: ExecutionPlan

    @property
    def review_required(self) -> bool:
        return bool(self.review_reasons)


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


KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
SOURCE_REGISTRY = KNOWLEDGE_ROOT / "source_registry.json"
FACT_CATALOG = KNOWLEDGE_ROOT / "fact_catalog.json"
SUPPORT_PACK = KNOWLEDGE_ROOT / "rulepacks" / "ksure_mvp_candidates.json"
COMPLIANCE_PACK = KNOWLEDGE_ROOT / "rulepacks" / "fx_compliance_mvp.json"
RULEPACKS = (SUPPORT_PACK, COMPLIANCE_PACK)

#: Which rulepack answers which worker. Routing (§4.2[2]) is implemented by
#: loading only the packs the plan selected, so an unplanned worker's rules are
#: never evaluated — as opposed to evaluated and then filtered out of the
#: answer, which would leave them in the packet and in its identity.
PACK_FOR_WORKER = {SUPPORT: SUPPORT_PACK, COMPLIANCE: COMPLIANCE_PACK}


@lru_cache(maxsize=4)
def _knowledge_pipeline(packs: tuple[Path, ...]) -> TradeFlowPipeline:
    """Load a pipeline over exactly these rulepacks.

    Cached per pack set: a web process sees at most the four combinations the
    routing table can produce, and rebuilding the repository per request would
    re-read and re-parse every rule file.
    """
    knowledge = KnowledgeRepository.from_json_files(SOURCE_REGISTRY, packs)
    return TradeFlowPipeline(
        knowledge,
        fact_assembler=FactAssembler(FactCatalog.from_json(FACT_CATALOG)),
    )


def _default_knowledge_pipeline() -> TradeFlowPipeline:
    """Every rulepack — the shape callers outside routing still expect."""
    return _knowledge_pipeline(RULEPACKS)


@lru_cache(maxsize=1)
def _default_knowledge_files() -> tuple[InputFile, ...]:
    """Fingerprint the rule files the default pipeline was built from.

    Cached alongside the pipeline because they describe the same load: a
    process that re-read the files would also rebuild the repository.
    """
    return fingerprint_knowledge(
        repo_root=REPO_ROOT,
        source_registry=SOURCE_REGISTRY,
        rulepacks=RULEPACKS,
        fact_catalog=FACT_CATALOG,
    )



STRUCTURE_EVIDENCE_ID = "TRADEFLOW_DERIVED_STRUCTURE"
DECLARED_COMPANY_EVIDENCE_ID = "TRADEFLOW_COMPANY_DECLARED"

#: The company facts §5.4's eligibility rules will not read without evidence.
#: Everything else on the profile reaches the rulepack conditions directly; these
#: three go through `KsureCaseProfile`, which refuses a fact that cannot say
#: where it came from.
DECLARED_COMPANY_FIELDS = (
    "company.size",
    "company.credit_issue_free",
    "company.ksure_exporter_grade",
)


def _structure_assertions(
    program: TradeProgram,
    structure: Mapping[str, Any],
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest the structure facts this module computed, or attest nothing.

    The rules refuse a fact without evidence of the role the catalog demands,
    which is the point: a day count that arrived from nowhere would be
    indistinguishable from one the user stated. These came from a subtraction
    over dates the user gave, so the evidence says `calculation` and names this
    module — and `generated_at` is passed explicitly so re-running the same
    analysis produces the same packet identity (ADR-0007).
    """
    empty = {case.case_id: () for case in program.cases}
    if not structure:
        return empty, ()

    case_ids = tuple(case.case_id for case in program.cases)
    descriptor = EvidenceDescriptor(
        STRUCTURE_EVIDENCE_ID,
        EvidenceRole.CALCULATION,
        case_ids,
        generated_at=as_of,
        payload={"facts": dict(structure)},
    )
    assertions = {
        case_id: tuple(
            FactAssertion(field, value, (STRUCTURE_EVIDENCE_ID,))
            for field, value in structure.items()
        )
        for case_id in case_ids
    }
    return assertions, (descriptor,)


def _declared_company_assertions(
    program: TradeProgram,
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest the company facts the company itself stated.

    These arrive from the signed-in account, which is to say from the company.
    That is a weaker kind of evidence than a snapshot of an official source, and
    the descriptor says so rather than dressing it up: the role is the one the
    eligibility catalog demands, but the payload names the account as the
    declarer. A judgement resting on it still carries `review_required`, because
    "우리는 중소기업입니다"라는 자기 선언으로 보험 자격을 확정할 수는 없다.

    An unstated fact produces no assertion at all — the rules then report it as
    missing, which is the answer, not a gap to be filled with `False`.
    """
    empty = {case.case_id: () for case in program.cases}
    facts = program.company.facts()
    declared = {
        field: facts[field]
        for field in DECLARED_COMPANY_FIELDS
        if facts.get(field) is not None
    }
    if not declared:
        return empty, ()

    case_ids = tuple(case.case_id for case in program.cases)
    descriptor = EvidenceDescriptor(
        DECLARED_COMPANY_EVIDENCE_ID,
        EvidenceRole.SUPPORT_ELIGIBILITY,
        case_ids,
        generated_at=as_of,
        payload={
            "facts": dict(declared),
            "declared_by": program.company.company_id,
            "basis": "기업이 계정에 직접 입력한 사실",
        },
    )
    assertions = {
        case_id: tuple(
            FactAssertion(field, value, (DECLARED_COMPANY_EVIDENCE_ID,))
            for field, value in declared.items()
        )
        for case_id in case_ids
    }
    return assertions, (descriptor,)


def analyze(
    program: TradeProgram,
    *,
    snapshot_root: Path | str,
    baseline_profit: Decimal | None = None,
    profit_floor: Decimal | None = None,
    hedge_measures: tuple[HedgeMeasure, ...] = (),
    knowledge_pipeline: TradeFlowPipeline | None = None,
    utterance: str | None = None,
    as_of: datetime | None = None,
) -> Analysis:
    """Run the workers this program calls for, keeping failures contained."""
    report = WorkerReport()
    review: list[str] = []
    evaluated_at = as_of or datetime.now(UTC)

    exposures = analyze_exposure(program)
    report.completed.append("exposure")
    cashflow = project_cashflow_analysis(exposures)

    # What the trades themselves say about their structure. The four facts
    # only the company can state (netting and friends) are not here; see
    # routing.DECLARED_STRUCTURE_FIELDS.
    structure = derive_structure(program)

    # §4.2[2]: decide the call plan before calling anything. Exposure has
    # already run because every other decision reads its result.
    plan = plan_execution(
        program,
        exposures,
        company_facts=program.company.facts(),
        trade_structure=structure,
        baseline_profit=baseline_profit,
        profit_floor=profit_floor,
        has_usable_measure=bool(usable_measures(hedge_measures)),
        intent=read_intent(utterance),
    )
    report.skipped.update(plan.skipped())

    verification = _isolated(
        report,
        "source_verification",
        lambda: load_source_verification(
            snapshot_root, as_of=evaluated_at
        ),
    )
    verification_ref, source_freshness = verification or (None, None)
    if source_freshness is not None:
        report.completed.append("source_verification")
    else:
        review.append(
            "공식 출처 검증 기록을 읽지 못해 규칙 판정을 자동으로 확정할 수 "
            "없습니다"
        )

    knowledge_workers = tuple(
        name for name in (SUPPORT, COMPLIANCE) if plan.runs(name)
    )
    decision_packet = None
    if knowledge_workers:
        # Only the planned packs are loaded, so an unplanned worker's rules do
        # not reach the evaluation at all.
        pipeline = knowledge_pipeline or _knowledge_pipeline(
            tuple(PACK_FOR_WORKER[name] for name in knowledge_workers)
        )
        evaluated_at_utc = as_of or datetime.now(UTC)
        assertions, structure_evidence = _structure_assertions(
            program, structure, as_of=evaluated_at_utc
        )
        declared, declared_evidence = _declared_company_assertions(
            program, as_of=evaluated_at_utc
        )
        assertions = {
            case_id: (*assertions.get(case_id, ()), *declared.get(case_id, ()))
            for case_id in {*assertions, *declared}
        }
        structure_evidence = (*structure_evidence, *declared_evidence)
        decision_packet = _isolated(
            report,
            "knowledge",
            lambda: pipeline.analyze_case_packet(
                program,
                assertions_by_case=assertions,
                evidence=structure_evidence,
                source_freshness=source_freshness,
            ),
        )
        if decision_packet is not None:
            report.completed.extend(knowledge_workers)
            review.extend(decision_packet.review_reasons)
        else:
            review.append(
                "지원제도와 신고의무 규칙을 실행하지 못해 전문가 검토가 "
                "필요합니다"
            )
    else:
        # Not run is not "nothing to report". §5.5's filing duties arise only
        # from trade structures the user has to tell us about, and staying
        # quiet about that would read as a clearance.
        review.append(plan.skipped()[COMPLIANCE])

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
        path = latest_snapshot_path(snapshot_root, FX_SOURCE)
        ref, payload = read_snapshot(path)
        snapshot = ref
        require_fresh(ref, FX_FRESHNESS, evaluated_at)
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

    if band is None:
        # Whatever the plan was waiting for, no input the user can type
        # produces a hedge ratio without a scenario band. Asking for profit
        # here would send them off to do work that changes nothing, so the
        # market failure is the reason reported and nothing is requested.
        report.skipped["hedge"] = "환율 시나리오가 없어 헤지비율을 계산할 수 없습니다"
    elif not plan.runs(HEDGE):
        # The plan already recorded the reason and what it is waiting for.
        required_inputs.extend(plan.requires())
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
        snapshot, evaluated_at
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
        plan=plan,
        versions=CalculationVersions(
            formula_version=FORMULA_VERSION,
            packet_schema_version=(
                decision_packet.schema_version
                if decision_packet is not None
                else None
            ),
            # An injected pipeline was built from files this module never saw,
            # so claiming the default fingerprints would be a lie. An empty
            # list reads as "not recorded", which is what happened.
            knowledge_files=(
                () if knowledge_pipeline is not None else _default_knowledge_files()
            ),
            snapshots=snapshot_versions(
                (*program.input_snapshots, snapshot, verification_ref)
            ),
            business_inputs=canonical_business_inputs(
                program=program,
                baseline_profit=baseline_profit,
                profit_floor=profit_floor,
                hedge_measures=hedge_measures,
                evaluated_at=evaluated_at,
                horizon_business_days=horizon,
            ),
        ),
    )
