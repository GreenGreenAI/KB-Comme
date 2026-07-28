"""The intake agent: turn what the user said into cases, or ask for the rest.

§4.2[1] gives this agent three jobs and no others — pick what to pass the slot
validator, read back what it returns, and stop the pipeline when a required slot
is missing. It never invents a value: an amount nobody stated is asked for, not
assumed.

This is the most frequently triggered agent in the product. The people it serves
do not know their own exposure, so a session that begins complete is the
exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.tools.slots import SlotIssue, SlotReading, read_slots


@dataclass(frozen=True)
class IntakeResult:
    """Either a program ready to analyse, or the questions blocking it."""

    program: TradeProgram | None
    questions: tuple[str, ...]
    #: (slot, question) in the order they should be asked. `questions` is the
    #: wording alone, kept for callers that only render prose.
    prompts: tuple[tuple[str, str], ...]
    missing: tuple[str, ...]
    issues: tuple[SlotIssue, ...]
    readings: tuple[SlotReading, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return self.program is not None


def _case(index: int, values: Mapping[str, Any]) -> TradeCase:
    direction = TradeDirection(values["direction"])
    prefix = "EXPORT" if direction is TradeDirection.EXPORT else "IMPORT"
    return TradeCase(
        case_id=f"{prefix}-{index:03d}",
        direction=direction,
        currency=values["currency"],
        amount=Decimal(values["amount"]),
        expected_payment_date=values["expected_payment_date"],
        payment_method=PaymentMethod(values["payment_method"].lower()),
        counterparty_country=values.get("country"),
        attributes={
            key: values[key]
            for key in ("counterparty_id", "expected_shipment_date",
                        "advance_payment_ratio", "contract_date")
            if key in values
        } | dict(values.get("case_facts", {})),
    )


def intake(
    cases: list[Mapping[str, Any]],
    *,
    company: CompanyProfile | None = None,
    company_name: str = "미입력 기업",
    is_sme: bool | None = None,
    opening_balances: Mapping[str, Any] | None = None,
    as_of: date | None = None,
    program_id: str = "SESSION",
) -> IntakeResult:
    """Read every case, and stop the pipeline if any of them is incomplete.

    Questions from all incomplete cases are merged and capped, so a user filling
    in three trades is not asked nine things at once.

    `company` is the profile an account already holds, facts and all. It wins
    over the loose `company_name`/`is_sme` arguments, which remain for callers
    with no account to speak of — those two are all a request body can state,
    and §5.4 reads more than two facts.
    """
    if not cases:
        return IntakeResult(
            program=None,
            questions=("어떤 거래를 분석할까요? 수출인지 수입인지, 금액과 결제일을 알려주세요.",),
            prompts=(),
            missing=("direction", "amount", "expected_payment_date"),
            issues=(),
        )

    readings = tuple(read_slots(case) for case in cases)
    missing: list[str] = []
    issues: list[SlotIssue] = []
    prompts: list[tuple[str, str]] = []
    questions: list[str] = []
    for reading in readings:
        for slot in reading.missing:
            if slot not in missing:
                missing.append(slot)
        issues.extend(reading.issues)
        for slot, question in reading.prompts():
            if question not in questions:
                questions.append(question)
                prompts.append((slot, question))

    if missing or issues:
        return IntakeResult(
            program=None,
            questions=tuple(questions[:3]),
            prompts=tuple(prompts[:3]),
            missing=tuple(missing),
            issues=tuple(issues),
            readings=readings,
        )

    balances = {
        str(currency).upper(): Decimal(str(amount))
        for currency, amount in (opening_balances or {}).items()
        if str(amount).strip() != ""
    }
    program = TradeProgram(
        program_id=program_id,
        company=company or CompanyProfile("COMPANY-001", company_name, is_sme=is_sme),
        cases=tuple(
            _case(index, reading.values)
            for index, reading in enumerate(readings, start=1)
        ),
        opening_balances=balances,
        as_of=as_of or date.today(),
    )
    return IntakeResult(
        program=program,
        questions=(),
        prompts=(),
        missing=(),
        issues=(),
        readings=readings,
    )
