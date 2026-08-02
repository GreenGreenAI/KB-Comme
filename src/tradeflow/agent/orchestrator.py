"""Deciding which workers to run, and surviving the ones that fail.

§4.2[2] keeps this rule-based until all five workers exist; the LLM takes over
the routing decision only once there is something to route. What it does own
today is failure isolation (§9.3): a worker that fails must not take the answer
down with it, and must not be papered over either — the gap is reported as
missing information rather than filled in.
"""

from __future__ import annotations

import logging

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
    derive_payment_terms,
    derive_structure,
    EXPOSURE,
    HEDGE,
    MARKET,
    SUPPORT,
    ExecutionPlan,
    plan_execution,
)
from tradeflow.runtime import asking
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
from tradeflow.runtime import observing
from tradeflow.tools.intent import read_intent
from tradeflow.tools.utterance import financing_purpose, payment_structure
from tradeflow.domain.datasets import (
    SnapshotDataset,
    parse_ksure_country_policy_payload,
)
from tradeflow.domain.snapshot_file import SnapshotNotFoundError
from tradeflow.knowledge.facts import FactContractError
from tradeflow.knowledge.ksure import KsureCaseProfile, bind_country_policy
from tradeflow.tools.source_freshness import load_source_verification
from tradeflow.tools.volatility import (
    ScenarioBand,
    estimate_volatility,
    require_fresh,
    scenario_band,
)

logger = logging.getLogger("tradeflow.orchestrator")

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
    #: Seconds each worker took, whether or not it produced anything. A worker
    #: that failed after five seconds and one that failed immediately are
    #: different problems, and the report used to keep only the failure.
    took: dict[str, float] = field(default_factory=dict)

    def missing_information(self) -> tuple[str, ...]:
        return tuple(
            f"{name}: {reason}"
            for name, reason in (*self.failed.items(), *self.skipped.items())
        )


def _isolated(report: WorkerReport, name: str, run: Callable[[], Any]) -> Any | None:
    """Run one worker, recording a failure instead of propagating it (§9.3).

    Also how long it took. This is the only place every worker passes through,
    so measuring here costs one wrapper and covers all of them — and until it
    existed, the answer to "which worker is slow" was to time the whole request
    by hand. §4.2[9] took nineteen seconds for a week before anyone noticed.
    """
    with observing.took(report.took, name):
        try:
            result = run()
        except Exception as exc:  # noqa: BLE001 — a worker failure must be survivable
            report.failed[name] = f"{type(exc).__name__}: {exc}"
            logger.warning("워커 실패 %s: %s", name, exc)
            return None
    logger.info("워커 %s %.3fs", name, report.took[name])
    return result


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
    #: The §5.5 facts the company stated in words. Carried so the answer can
    #: tell a rule that is waiting on a detail apart from one that does not
    #: know whether it applies at all — nineteen rules run either way, and
    #: without this they arrive as one undifferentiated list.
    declared_structure: Mapping[str, bool] = field(default_factory=dict)

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

#: What the company said the money is for. Separate from the company
#: declaration above because it comes from the sentence, not the account.
DECLARED_FINANCING_EVIDENCE_ID = "TRADEFLOW_FINANCING_DECLARED"

#: The payment term, subtracted from the shipment and payment dates the
#: company gave. Its own descriptor because the catalog demands `user_trade`
#: for that field, and the derived-structure evidence attests `calculation`.
PAYMENT_TERM_EVIDENCE_ID = "TRADEFLOW_PAYMENT_TERM_DERIVED"

#: What the company answered when §5.4 asked for it. One per evidence role,
#: because the fact catalog fixes the role per field and a single descriptor
#: would have to claim one of them for facts the rules read differently.
ANSWERED_EVIDENCE_PREFIX = "TRADEFLOW_ANSWERED_"

#: The §5.5 declarations the company made in the sentence. Separate from the
#: structure this module computes: those came from a subtraction over dates,
#: these came from the company saying so.
DECLARED_STRUCTURE_EVIDENCE_ID = "TRADEFLOW_STRUCTURE_DECLARED"

#: K-SURE's country acceptance policy, as a snapshot. The source is registered
#: and the binder is written and tested; what is absent is the snapshot itself,
#: so this reads as "no snapshot" and the rules report the fact as missing.
#: That is the correct answer today — inventing a policy for Brazil would be
#: exactly the guess §5.4 refuses.
COUNTRY_POLICY_SOURCE = "KSURE_COUNTRY_POLICY_API"

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


def _country_policy_assertions(
    program: TradeProgram,
    snapshot_root: Path | str,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Bind each case's counterparty country to K-SURE's acceptance policy.

    `bind_country_policy` has existed, with tests, since the country catalog
    landed — but nothing called it outside those tests, so a trade that named
    Brazil was analysed as a trade that named nowhere. Wiring it here means the
    judgement opens the moment the snapshot exists, with no further code.

    Absent snapshot, absent country and an unlisted country all end the same
    way: no assertion, and §5.4 reports `counterparty.country_restricted` as a
    fact it does not have. A country policy is the kind of thing that must be
    dated and re-verifiable, and there is no defensible default for it.
    """
    empty = {case.case_id: () for case in program.cases}
    cases = [case for case in program.cases if case.counterparty_country]
    if not cases:
        return empty, ()

    try:
        path = latest_snapshot_path(snapshot_root, COUNTRY_POLICY_SOURCE)
        ref, payload = read_snapshot(path)
        catalog = parse_ksure_country_policy_payload(payload)
    except (SnapshotNotFoundError, OSError, ValueError, TypeError):
        return empty, ()

    dataset = SnapshotDataset(ref=ref, value=catalog)
    assertions = dict(empty)
    evidence: list[EvidenceDescriptor] = []
    for case in cases:
        try:
            bound, descriptor = bind_country_policy(KsureCaseProfile(), dataset, case)
        except FactContractError:
            # An unlisted country is not a permissive one. Saying nothing lets
            # the rule report the gap, which is the honest outcome.
            continue
        assertions[case.case_id] = (
            FactAssertion(
                "counterparty.country_restricted",
                bound.country_restricted,
                (descriptor.evidence_id,),
            ),
        )
        evidence.append(descriptor)
    return assertions, tuple(evidence)


def _declared_company_assertions(
    program: TradeProgram,
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest the company facts the company itself stated.

    These arrive from the signed-in account, which is to say from the company.
    That is a weaker kind of evidence than a snapshot of an official source, so
    it has its own role instead of borrowing `SUPPORT_ELIGIBILITY`. The fact
    assembler may use it to produce a candidate, while the pipeline keeps the
    authoritative evidence requirement open and forces review. A judgement
    resting on it still carries `review_required`, because
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
        EvidenceRole.USER_DECLARATION,
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


@dataclass(frozen=True)
class MarketNow:
    """Today's rate and the window it was read over, with its snapshot.

    §4.2[4]'s band needs a horizon, and a horizon needs a payment date — but
    the rate itself and the volatility behind it need no trade at all. They
    were being withheld anyway, because intake gated every worker on a trade
    the user had not described yet: "환율이 요즘 어때?" was answered with a
    request for the amount and the settlement date.
    """

    spot_rate: Decimal
    observed_on: date
    annualized_volatility: float
    window: int
    first_observed: date
    last_observed: date
    source_id: str
    version: str


def market_now(
    snapshot_root: Path | str,
    *,
    as_of: datetime | None = None,
) -> MarketNow:
    """The published rate and the realized volatility around it.

    Same snapshot, same freshness policy and same estimator the band uses, so
    a number said here cannot disagree with the same number said in an answer.
    Staleness raises rather than degrading: §4.2[4] makes it the stopping
    condition, and a rate quoted without one is worse than no rate.
    """
    evaluated_at = as_of or datetime.now(UTC)
    path = latest_snapshot_path(
        snapshot_root,
        FX_SOURCE,
        as_of=evaluated_at,
    )
    ref, payload = read_snapshot(path)
    require_fresh(ref, FX_FRESHNESS, evaluated_at)
    observations = usd_krw_series(payload)
    estimate = estimate_volatility(observations)
    observed_on, spot = observations[-1]
    return MarketNow(
        spot_rate=spot,
        observed_on=observed_on,
        annualized_volatility=estimate.annualized,
        window=estimate.window,
        first_observed=estimate.first_observed,
        last_observed=estimate.last_observed,
        source_id=ref.source_id,
        version=ref.version,
    )


def _declared_structure_assertions(
    program: TradeProgram,
    stated: Mapping[str, bool],
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest the trade structure the company described in words.

    §5.5's compliance worker has been skipped on every request this product has
    served, because the four declarations it routes on were filled by nothing.
    Its skip reason asks for 상계·제3자 지급·상호계산 — and the sentence it was
    answering said 「상계로 처리하는데 신고 대상인가요」. Nineteen rules were
    loaded and ready the whole time.

    The catalog fixes the evidence role at `compliance`, so that is what this
    carries. It is the company's own word, which is why the judgement resting
    on it stays reviewable — but §5.5 was never asking for proof, it was asking
    to be told.
    """
    empty = {case.case_id: () for case in program.cases}
    if not stated:
        return empty, ()

    case_ids = tuple(case.case_id for case in program.cases)
    descriptor = EvidenceDescriptor(
        DECLARED_STRUCTURE_EVIDENCE_ID,
        EvidenceRole.COMPLIANCE,
        case_ids,
        generated_at=as_of,
        payload={
            "facts": dict(stated),
            "declared_by": program.company.company_id,
            "basis": "기업이 문장으로 말한 거래 구조",
        },
    )
    assertions = {
        case_id: tuple(
            FactAssertion(field, value, (DECLARED_STRUCTURE_EVIDENCE_ID,))
            for field, value in stated.items()
        )
        for case_id in case_ids
    }
    return assertions, (descriptor,)


def _declared_financing_assertions(
    program: TradeProgram,
    utterance: str | None,
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest the purpose the company stated for the money it needs.

    §5.4's 수출신용보증(선적전) rule has three conditions this program can meet
    — 중소·중견기업, 수출 거래, 보증대상 자금 — and the third was never
    supplied by anything, so a company asking about 제작 자금 was told about
    its exchange-rate exposure instead. The rule was there the whole time.

    It is the company's own word, so the judgement resting on it stays
    `review_required`. Saying nothing when the
    sentence names no purpose is the right answer, not a gap: the rule then
    reports 보증대상 자금 as missing, which is a question the user can answer.
    """
    empty = {case.case_id: () for case in program.cases}
    purpose = financing_purpose(utterance)
    if purpose is None:
        return empty, ()

    case_ids = tuple(case.case_id for case in program.cases)
    descriptor = EvidenceDescriptor(
        DECLARED_FINANCING_EVIDENCE_ID,
        # `user_trade`, not `user_declaration`: the fact catalog fixes the role
        # per field, and this one is the company describing its own trade.
        EvidenceRole.USER_TRADE,
        case_ids,
        generated_at=as_of,
        payload={
            "facts": {"financing.purpose": purpose},
            "declared_by": program.company.company_id,
            "basis": "기업이 문장으로 말한 자금 용도",
        },
    )
    assertions = {
        case_id: (
            FactAssertion(
                "financing.purpose", purpose, (DECLARED_FINANCING_EVIDENCE_ID,)
            ),
        )
        for case_id in case_ids
    }
    return assertions, (descriptor,)


def _payment_term_assertions(
    program: TradeProgram,
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest the payment term this module subtracted out of the user's dates.

    `user_trade`, not `calculation`, and the catalog is why — it fixes the role
    per field, and for this one it says the term is a fact about the trade. The
    two inputs are the company's own dates, so what the evidence attests is
    still the company's trade; the payload carries the arithmetic so the audit
    can see it was subtracted rather than stated.

    That is the whole difference from asking. A term the company typed could
    disagree with the dates beside it on screen, and nothing would say which
    one the rule used.
    """
    empty = {case.case_id: () for case in program.cases}
    terms = derive_payment_terms(program)
    if not terms:
        return empty, ()

    case_ids = tuple(case.case_id for case in program.cases)
    descriptor = EvidenceDescriptor(
        PAYMENT_TERM_EVIDENCE_ID,
        EvidenceRole.USER_TRADE,
        case_ids,
        generated_at=as_of,
        payload={
            "facts": dict(sorted(terms.items())),
            "declared_by": program.company.company_id,
            "basis": "기업이 말한 선적일과 결제일의 차이",
        },
    )
    assertions = {
        case_id: tuple(
            FactAssertion(field, value, (PAYMENT_TERM_EVIDENCE_ID,))
            for field, value in sorted(terms.items())
        )
        for case_id in case_ids
    }
    return assertions, (descriptor,)


def _answered_fact_assertions(
    program: TradeProgram,
    answered: Mapping[str, str] | None,
    *,
    as_of: datetime,
) -> tuple[dict[str, tuple[FactAssertion, ...]], tuple[EvidenceDescriptor, ...]]:
    """Attest what the company answered when a rule asked for it.

    §5.4 already reported which facts it was short of; nothing carried the
    answers back. So a company could be asked for its K-SURE grade, type it in,
    and watch the same product come back 「아직 판정하지 못했습니다」 — the
    question was real and the answer went nowhere.

    The role is read from the fact catalog, one descriptor per role. Choosing
    it here would be this module deciding what kind of evidence a company's
    word is, and the catalog decides that per field precisely so the answer
    cannot change with the caller: a grade is `support_eligibility`, a purpose
    is `user_trade`, a bank consultation is `procedure`.

    Anything the catalog does not recognise never arrives — the web layer
    refuses it at the door — so an unknown field here is a bug rather than an
    input, and it is dropped rather than guessed at.
    """
    empty = {case.case_id: () for case in program.cases}
    if not answered:
        return empty, ()

    by_role: dict[str, dict[str, Any]] = {}
    for field, value in answered.items():
        role = asking.evidence_role(field)
        if role is None or not asking.accepts(field, value):
            continue
        by_role.setdefault(role, {})[field] = asking.as_stated(field, value)
    if not by_role:
        return empty, ()

    case_ids = tuple(case.case_id for case in program.cases)
    descriptors: list[EvidenceDescriptor] = []
    assertions: dict[str, list[FactAssertion]] = {case_id: [] for case_id in case_ids}
    for role, facts in sorted(by_role.items()):
        evidence_id = f"{ANSWERED_EVIDENCE_PREFIX}{role.upper()}"
        descriptors.append(
            EvidenceDescriptor(
                evidence_id,
                EvidenceRole(role),
                case_ids,
                generated_at=as_of,
                payload={
                    "facts": dict(sorted(facts.items())),
                    "declared_by": program.company.company_id,
                    "basis": "규칙이 물은 사실에 기업이 답한 값",
                },
            )
        )
        for case_id in case_ids:
            assertions[case_id].extend(
                FactAssertion(field, value, (evidence_id,))
                for field, value in sorted(facts.items())
            )
    return (
        {case_id: tuple(items) for case_id, items in assertions.items()},
        tuple(descriptors),
    )


def analyze(
    program: TradeProgram,
    *,
    snapshot_root: Path | str,
    baseline_profit: Decimal | None = None,
    profit_floor: Decimal | None = None,
    hedge_measures: tuple[HedgeMeasure, ...] = (),
    knowledge_pipeline: TradeFlowPipeline | None = None,
    utterance: str | None = None,
    #: What the conversation is still about, when this turn carries no
    #: sentence of its own. Answering a request panel sends values and no
    #: words, and reading intent from that blank reordered the answer back to
    #: the default the moment the user supplied what was asked for — the
    #: judgement they came for closed itself as it arrived.
    #:
    #: Ordering only. Facts are read from `utterance`, never from this: a
    #: sentence already answered must not declare its trade a second time.
    intent: tuple[str, ...] | None = None,
    #: What the company answered to the questions §5.4's rules raised. Read
    #: through the fact catalog — see `_answered_fact_assertions`.
    answered_facts: Mapping[str, str] | None = None,
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
    # Two sources, kept apart. `derive_structure` subtracts dates the user
    # gave, so its evidence says `calculation`; the declarations came from the
    # company saying so, and the catalog fixes their role at `compliance`. The
    # merged mapping is for routing only — asserting a field from both would be
    # the same fact arriving twice, which the fact assembler refuses.
    derived_structure = derive_structure(program)
    declared_structure = payment_structure(utterance)
    structure = {**derived_structure, **declared_structure}

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
        intent=intent if intent is not None else read_intent(utterance),
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
            program, derived_structure, as_of=evaluated_at_utc
        )
        declared, declared_evidence = _declared_company_assertions(
            program, as_of=evaluated_at_utc
        )
        stated, stated_evidence = _declared_structure_assertions(
            program, declared_structure, as_of=evaluated_at_utc
        )
        financing, financing_evidence = _declared_financing_assertions(
            program, utterance, as_of=evaluated_at_utc
        )
        country, country_evidence = _country_policy_assertions(program, snapshot_root)
        answered, answered_evidence = _answered_fact_assertions(
            program, answered_facts, as_of=evaluated_at_utc
        )
        terms, term_evidence = _payment_term_assertions(
            program, as_of=evaluated_at_utc
        )
        assertions = {
            case_id: (
                *assertions.get(case_id, ()),
                *declared.get(case_id, ()),
                *stated.get(case_id, ()),
                *financing.get(case_id, ()),
                *country.get(case_id, ()),
                *answered.get(case_id, ()),
                *terms.get(case_id, ()),
            )
            for case_id in {
                *assertions, *declared, *stated, *financing, *country,
                *answered, *terms,
            }
        }
        structure_evidence = (
            *structure_evidence,
            *declared_evidence,
            *stated_evidence,
            *financing_evidence,
            *country_evidence,
            *answered_evidence,
            *term_evidence,
        )
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
        path = latest_snapshot_path(
            snapshot_root,
            FX_SOURCE,
            as_of=evaluated_at,
        )
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
        declared_structure=declared_structure,
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
