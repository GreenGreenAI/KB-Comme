"""Deciding which workers to call, and recording why the others were not.

§4.2[2] gives the orchestrator one job — produce an `execution_plan` — and a
routing table to produce it from. Until now every worker ran on every request,
which is not a plan but its absence, and it cost the answer its usefulness: a
plain T/T export drew nineteen filing rules, every one of them presuming a
trade structure the user had never mentioned, and every one returning
`INSUFFICIENT_INFORMATION`.

Nineteen "we cannot tell" is not more cautious than one "tell us if you do
netting". It is the same information, spread until nobody reads it.

The rule that matters here is the one about *not running*. A compliance worker
that quietly does not run reads as "no filing needed", which is the one
conclusion this product must never imply by omission. So a skipped worker is
never silent: it carries what would make it run, in the same field §9.3 uses
for failures, and the answer says it out loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from tradeflow.domain.enums import TradeDirection
from tradeflow.domain.models import CurrencyExposure, TradeProgram
from tradeflow.tools.intent import describe

#: The trade structures §5.5's rules are about. Every one of the nineteen
#: filing rules is gated on one of these.
#:
#: They divide by who can establish them. The two period fields fall out of the
#: dates the user already gave, so the orchestrator computes them and attests
#: them with calculation evidence. The other four — netting, third-party
#: payment, a mutual account, paying outside a foreign-exchange bank — are
#: facts only the company knows, and the fact catalog requires *compliance*
#: evidence for them. Whether a company's own statement can carry that role is
#: a knowledge-layer policy question (issue #9), so they are named here but not
#: yet accepted as input: routing on a declaration we then cannot pass to the
#: rules would repeat the "heard it and dropped it" defect.
DERIVED_STRUCTURE_FIELDS = (
    "trade.days_before_shipment",
    "trade.days_before_receipt",
)

DECLARED_STRUCTURE_FIELDS = (
    "payment.is_netting",
    "payment.is_third_party",
    "payment.uses_mutual_account",
    "payment.uses_foreign_exchange_bank",
)

STRUCTURE_FIELDS = DERIVED_STRUCTURE_FIELDS + DECLARED_STRUCTURE_FIELDS

#: Company facts §5.4's eligibility rules read. A profile stating none of them
#: cannot produce a judgement, only a list of things it would need.
PROFILE_FIELDS = (
    "company.size",
    "company.is_sme",
    "company.credit_issue_free",
    "company.ksure_exporter_grade",
    "company.is_domestic",
)

EXPOSURE = "exposure"
MARKET = "market_scenario"
SUPPORT = "support"
COMPLIANCE = "compliance"
HEDGE = "hedge"


@dataclass(frozen=True)
class WorkerDecision:
    """Whether one worker is in the plan, and what it is waiting for."""

    name: str
    run: bool
    reason: str = ""
    #: Inputs the caller can ask the user for. Empty when nothing the user
    #: could type would change the decision.
    requires: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run and not self.reason:
            raise ValueError(
                f"{self.name}: a worker left out of the plan must say what "
                "would put it in — silence reads as 'nothing to report'"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker": self.name,
            "run": self.run,
            "reason": self.reason,
            "requires": list(self.requires),
        }


@dataclass(frozen=True)
class ExecutionPlan:
    """§4.2[2]'s output: the workers to call, and why the rest were not."""

    decisions: tuple[WorkerDecision, ...]
    #: §4.2[2]'s third input. It is carried, not applied: see plan_execution.
    intent: tuple[str, ...] = ()

    def runs(self, name: str) -> bool:
        return any(item.name == name and item.run for item in self.decisions)

    def requires(self) -> tuple[str, ...]:
        """Everything the plan is waiting on, in the order it was decided."""
        return tuple(
            field
            for item in self.decisions
            if not item.run
            for field in item.requires
        )

    def skipped(self) -> dict[str, str]:
        return {
            item.name: item.reason for item in self.decisions if not item.run
        }

    @property
    def empty(self) -> bool:
        """§4.2[2]'s stop condition: no worker can be called at all."""
        return not any(item.run for item in self.decisions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workers": [item.as_dict() for item in self.decisions],
            "planned": [item.name for item in self.decisions if item.run],
            **describe(self.intent),
        }


def has_profile_facts(facts: Mapping[str, Any] | None) -> bool:
    """Whether the company profile states anything the rules can read."""
    if not facts:
        return False
    return any(
        facts.get(field) is not None and facts.get(field) != ""
        for field in PROFILE_FIELDS
    )


def known_structure(structure: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Which trade-structure facts are established well enough to judge on.

    A `False` counts. "이 거래는 선적 1년 전 수령이 아니다" is an answer, and
    the rules turn it into 해당없음 with a reason — a result, unlike the
    정보부족 an unestablished fact produces.
    """
    if not structure:
        return ()
    return tuple(
        field
        for field in STRUCTURE_FIELDS
        if structure.get(field) is not None and structure.get(field) != ""
    )


def derive_structure(program: TradeProgram) -> dict[str, int]:
    """Trade-structure facts that follow from dates the user already gave.

    §5.5 asks how far a payment falls before shipment (export) or before the
    goods are received (import); both are subtractions over dates intake
    already collected. Only the day count is produced here — the one-year
    threshold and the amount test belong to the rule, and duplicating them
    would put the same limit in two places that could drift apart.

    A case with no shipment date contributes nothing. Guessing one would
    manufacture a filing duty out of a blank field.
    """
    derived: dict[str, int] = {}
    for case in program.cases:
        shipment = case.attributes.get("expected_shipment_date")
        if not shipment:
            continue
        if isinstance(shipment, str):
            try:
                shipment = date.fromisoformat(shipment)
            except ValueError:
                continue
        gap = (shipment - case.expected_payment_date).days
        if gap <= 0:
            continue
        field = (
            "trade.days_before_shipment"
            if case.direction is TradeDirection.EXPORT
            else "trade.days_before_receipt"
        )
        # The longest gap decides: it is the one that can cross the threshold.
        derived[field] = max(derived.get(field, 0), gap)
    return derived


def derive_payment_terms(program: TradeProgram) -> dict[str, int]:
    """How long after shipment the money arrives, from the same two dates.

    §5.4's 단기수출보험(선적후·개별) asks whether the payment term is within two
    years. The company already said when it ships and when it is paid, and the
    term is the subtraction between them — asking for it would be the product
    failing to read its own input back, and the two answers could then
    disagree on screen.

    The mirror of `derive_structure`, which keeps the other sign: a payment
    landing *before* shipment is a prepayment and §5.5's question; one landing
    after is a term and §5.4's. Neither is invented from a blank shipment date.

    The longest term decides — it is the one that can cross the limit, and a
    shorter trade on the same program cannot make it safe.
    """
    terms: dict[str, int] = {}
    for case in program.cases:
        shipment = case.attributes.get("expected_shipment_date")
        if not shipment:
            continue
        if isinstance(shipment, str):
            try:
                shipment = date.fromisoformat(shipment)
            except ValueError:
                continue
        days = (case.expected_payment_date - shipment).days
        if days <= 0:
            continue
        terms["trade.payment_term_days"] = max(
            terms.get("trade.payment_term_days", 0), days
        )
    return terms


def _net_exposure(exposures: tuple[CurrencyExposure, ...]) -> Decimal:
    return sum(
        (item.trade_net_exposure for item in exposures), start=Decimal("0")
    )


def plan_execution(
    program: TradeProgram,
    exposures: tuple[CurrencyExposure, ...],
    *,
    company_facts: Mapping[str, Any] | None = None,
    trade_structure: Mapping[str, Any] | None = None,
    baseline_profit: Decimal | None = None,
    profit_floor: Decimal | None = None,
    has_usable_measure: bool = False,
    intent: tuple[str, ...] = (),
) -> ExecutionPlan:
    """Build the call plan from §4.2[2]'s routing table.

    Exposure is not in the plan: it has already run, because every other
    decision here reads its result.

    `intent` — §4.2[2]'s third input — is recorded and never subtracts from the
    plan. A question about the exchange rate does not stop this company having
    a filing duty, and a plan narrowed to what was asked would be the one shape
    of answer §2's user cannot benefit from: they came not knowing what to ask.
    What intent does change is the order the answer is read in (tools/intent).
    """
    decisions: list[WorkerDecision] = [
        WorkerDecision(EXPOSURE, True),
        # §4.2[2]: always. The band does not depend on anything the user has
        # to supply beyond the payment dates intake already required.
        WorkerDecision(MARKET, True),
    ]

    decisions.append(_support(company_facts))
    decisions.append(_compliance(trade_structure))
    decisions.append(
        _hedge(
            exposures,
            baseline_profit=baseline_profit,
            profit_floor=profit_floor,
            has_usable_measure=has_usable_measure,
        )
    )
    return ExecutionPlan(tuple(decisions), intent=tuple(intent))


def _support(company_facts: Mapping[str, Any] | None) -> WorkerDecision:
    """§4.2[2]: run when a company profile exists; §4.2[6] stops without one.

    Running it on an empty profile returns one INSUFFICIENT_INFORMATION per
    product — three cards saying nothing, where one sentence naming the two
    facts we need would let the user act.
    """
    if has_profile_facts(company_facts):
        return WorkerDecision(SUPPORT, True)
    return WorkerDecision(
        SUPPORT,
        False,
        "기업규모와 신용 상태를 알려주시면 K-SURE 환변동보험·단기수출보험·"
        "수출신용보증 자격을 판정합니다",
    )


def _compliance(
    trade_structure: Mapping[str, Any] | None,
) -> WorkerDecision:
    """§4.2[2]: run when the trade structure has netting, advance payment or
    an over-long period; §4.2[7] holds judgement without that information.

    The skip reason is written to be read as a question, not as a clearance.
    Nothing here concludes that no filing is due — it says we have not been
    given what the judgement needs.
    """
    known = known_structure(trade_structure)
    if known:
        return WorkerDecision(COMPLIANCE, True)
    return WorkerDecision(
        COMPLIANCE,
        False,
        "상계·제3자 지급·상호계산·선적 1년 초과 선수금 중 해당하는 것이 "
        "있으면 알려주세요. 외국환거래법 신고 의무는 이 거래 구조에서만 "
        "발생하므로, 알려주시기 전에는 신고 불필요로 판단하지 않습니다",
    )


def _hedge(
    exposures: tuple[CurrencyExposure, ...],
    *,
    baseline_profit: Decimal | None,
    profit_floor: Decimal | None,
    has_usable_measure: bool,
) -> WorkerDecision:
    """§4.2[2]: run when net exposure is non-zero.

    A fully offset position has nothing to hedge, and saying so is a result.

    Whether the scenario band exists is deliberately not checked here: the
    market worker has not run yet when the plan is built. A band that fails to
    materialise is a worker failure (§9.3), not a routing decision, and the two
    must not be spelled the same way.

    The remaining conditions are §4.2[5]'s stop conditions rather than routing,
    but they belong in the same list: the reader wants one place that says why
    a section is empty.

    §1.1's promise is carried in the words, not left to the screen. The screen
    had its own sentence saying the same thing, which asked for both values
    whichever one was missing and would have gone on asking after a condition
    here changed — a claim that lives in two places goes stale in the one
    further from the rule.
    """
    if _net_exposure(exposures) == 0:
        return WorkerDecision(
            HEDGE,
            False,
            "수취와 지급이 정확히 상계되어 잔여 환노출이 없습니다. "
            "헤지할 금액이 없습니다",
        )
    if baseline_profit is None:
        return WorkerDecision(
            HEDGE,
            False,
            "기준 영업이익을 알려주시면 헤지비율을 계산합니다. "
            "입력하지 않은 값을 임의로 만들지 않습니다",
            ("baseline_profit",),
        )
    if profit_floor is None:
        return WorkerDecision(
            HEDGE,
            False,
            "회사가 지키려는 목표 손익 하한을 알려주시면 헤지비율을 "
            "계산합니다. 입력하지 않은 하한을 임의로 만들지 않습니다",
            ("profit_floor",),
        )
    if not has_usable_measure:
        return WorkerDecision(
            HEDGE,
            False,
            "검증된 이용 가능 헤지 수단과 가격 정보가 없어 계산하지 않았습니다",
        )
    return WorkerDecision(HEDGE, True)
