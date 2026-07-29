"""Evidence-bound availability decisions for company-specific hedge quotes.

Public market data cannot establish the forward rate a bank actually offered
to one company. This module accepts a confirmed quote as user-supplied market
evidence, then permits it to reach the optimizer only when its company, side,
currency, maturity, notional and validity window exactly cover the program.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import (
    AvailabilityStatus,
    EvidenceRole,
    FinancialInstrumentKind,
    HedgeMeasureCategory,
    TradeDirection,
)
from tradeflow.domain.models import HedgeMeasure, TradeProgram
from tradeflow.domain.snapshot import require_aware
from tradeflow.knowledge.facts import FactContractError


USER_QUOTE_SOURCE_PREFIX = "USER_QUOTE"
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+\Z")


class HedgeQuoteSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class UserForwardQuote:
    """A confirmed forward quote offered to the program's company."""

    quote_id: str
    provider_id: str
    company_id: str
    case_ids: tuple[str, ...]
    base_currency: str
    counter_currency: str
    side: HedgeQuoteSide
    notional: Decimal
    contract_rate: Decimal
    cost_rate: Decimal
    settlement_date: date
    quoted_at: datetime
    valid_until: datetime
    confirmed: bool

    def __post_init__(self) -> None:
        for name in ("quote_id", "provider_id"):
            value = getattr(self, name)
            if not value or not _SAFE_ID.fullmatch(value):
                raise ValueError(
                    f"{name} must contain only letters, digits, '.', '_' or '-'"
                )
        if not self.company_id:
            raise ValueError("company_id is required")
        case_ids = tuple(self.case_ids)
        if not case_ids or len(case_ids) != len(set(case_ids)):
            raise ValueError("case_ids must be non-empty and unique")
        object.__setattr__(self, "case_ids", case_ids)

        base = self.base_currency.upper()
        counter = self.counter_currency.upper()
        if not re.fullmatch(r"[A-Z]{3}", base):
            raise ValueError("base_currency must be a three-letter code")
        if not re.fullmatch(r"[A-Z]{3}", counter):
            raise ValueError("counter_currency must be a three-letter code")
        if base == counter:
            raise ValueError("quote currencies must differ")
        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "counter_currency", counter)

        if not isinstance(self.side, HedgeQuoteSide):
            raise TypeError("side must be HedgeQuoteSide")
        for name in ("notional", "contract_rate", "cost_rate"):
            if not isinstance(getattr(self, name), Decimal):
                raise TypeError(f"{name} must be Decimal")
        if self.notional <= 0:
            raise ValueError("notional must be positive")
        if self.contract_rate <= 0:
            raise ValueError("contract_rate must be positive")
        if self.cost_rate < 0:
            raise ValueError("cost_rate must not be negative")
        quoted_at = require_aware(self.quoted_at, "quoted_at")
        valid_until = require_aware(self.valid_until, "valid_until")
        if valid_until < quoted_at:
            raise ValueError("valid_until must not precede quoted_at")
        if self.settlement_date < quoted_at.date():
            raise ValueError("settlement_date must not precede quoted_at")
        if self.confirmed is not True:
            raise ValueError("user forward quote must be explicitly confirmed")

    @property
    def source_id(self) -> str:
        return f"{USER_QUOTE_SOURCE_PREFIX}:{self.provider_id}:{self.quote_id}"


@dataclass(frozen=True)
class HedgeQuoteAvailabilityInput:
    """Measures plus the quote evidence from which they were decided."""

    measures: tuple[HedgeMeasure, ...]
    evidence: tuple[EvidenceDescriptor, ...]
    quote_ids_by_measure: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "measures", tuple(self.measures))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(
            self,
            "quote_ids_by_measure",
            MappingProxyType(dict(self.quote_ids_by_measure)),
        )


class UserQuoteHedgeAvailabilityService:
    """Apply exact-scope and freshness policy to user-confirmed quotes.

    ``evaluated_at`` is constructor input because the existing shared service
    protocol passes only an analysis date. Requiring both dates to agree keeps
    intraday quote expiry deterministic without silently changing that
    protocol.
    """

    def __init__(
        self,
        quotes: tuple[UserForwardQuote, ...],
        *,
        evaluated_at: datetime,
        selected_quote_id: str | None = None,
    ) -> None:
        self.quotes = tuple(quotes)
        self.evaluated_at = require_aware(evaluated_at, "evaluated_at")
        ids = [quote.quote_id for quote in self.quotes]
        if len(ids) != len(set(ids)):
            raise FactContractError("duplicate user hedge quote_id")
        if selected_quote_id is not None and selected_quote_id not in set(ids):
            raise FactContractError(
                f"selected hedge quote does not exist: {selected_quote_id}"
            )
        self.selected_quote_id = selected_quote_id

    def evaluate_measures(
        self,
        *,
        program: TradeProgram,
        as_of: date,
    ) -> tuple[HedgeMeasure, ...]:
        return self.assemble(program=program, as_of=as_of).measures

    def assemble(
        self,
        *,
        program: TradeProgram,
        as_of: date,
    ) -> HedgeQuoteAvailabilityInput:
        if self.evaluated_at.date() != as_of:
            raise FactContractError(
                "quote evaluation instant must fall on the analysis as_of date"
            )
        if program.as_of != as_of:
            raise FactContractError(
                "program as_of must match quote availability analysis date"
            )
        if not self.quotes:
            return HedgeQuoteAvailabilityInput(
                measures=(
                    HedgeMeasure(
                        measure_id="FORWARD_QUOTE_REQUIRED",
                        category=HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
                        kind=FinancialInstrumentKind.FORWARD,
                        status=AvailabilityStatus.INSUFFICIENT_INFORMATION,
                        status_reasons=(
                            "활성 상태로 확인된 기업별 선물환 호가가 필요합니다",
                        ),
                    ),
                ),
                evidence=(),
                quote_ids_by_measure={},
            )

        measures: list[HedgeMeasure] = []
        evidence: list[EvidenceDescriptor] = []
        quote_ids_by_measure: dict[str, str] = {}
        for quote in self.quotes:
            if quote.company_id != program.company.company_id:
                raise FactContractError(
                    f"{quote.quote_id}: quote company does not match program"
                )
            if quote.quoted_at > self.evaluated_at:
                raise FactContractError(
                    f"{quote.quote_id}: quote timestamp is in the future"
                )

            measure_id = f"FORWARD_QUOTE:{quote.provider_id}:{quote.quote_id}"
            reasons = self._inapplicability_reasons(quote, program)
            if self.evaluated_at > quote.valid_until:
                reasons.append("호가 유효시간이 만료되었습니다")
            if quote.settlement_date < self.evaluated_at.date():
                reasons.append("호가 결제일이 이미 지났습니다")

            selected = quote.quote_id == self.selected_quote_id
            if reasons:
                status = AvailabilityStatus.UNAVAILABLE
            elif self.selected_quote_id is None:
                status = AvailabilityStatus.CONDITIONAL
                reasons.append("사용할 호가를 명시적으로 선택해야 합니다")
            elif not selected:
                status = AvailabilityStatus.UNAVAILABLE
                reasons.append("이번 분석에 선택된 호가가 아닙니다")
            else:
                status = AvailabilityStatus.AVAILABLE

            measure = HedgeMeasure(
                measure_id=measure_id,
                category=HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
                kind=FinancialInstrumentKind.FORWARD,
                status=status,
                status_reasons=tuple(reasons),
                contract_rate=quote.contract_rate,
                cost_rate=quote.cost_rate,
                source_ids=(quote.source_id,),
            )
            measures.append(measure)
            quote_ids_by_measure[measure_id] = quote.quote_id
            evidence.append(self._descriptor(quote, measure))

        return HedgeQuoteAvailabilityInput(
            measures=tuple(measures),
            evidence=tuple(evidence),
            quote_ids_by_measure=quote_ids_by_measure,
        )

    def _inapplicability_reasons(
        self,
        quote: UserForwardQuote,
        program: TradeProgram,
    ) -> list[str]:
        cases_by_id = {case.case_id: case for case in program.cases}
        unknown = set(quote.case_ids) - set(cases_by_id)
        if unknown:
            raise FactContractError(
                f"{quote.quote_id}: quote references unknown cases: "
                + ", ".join(sorted(unknown))
            )

        reasons: list[str] = []
        if set(quote.case_ids) != set(cases_by_id):
            reasons.append(
                "현재 계산 엔진에서는 호가가 프로그램의 모든 거래를 포괄해야 합니다"
            )
        covered = [cases_by_id[case_id] for case_id in quote.case_ids]
        if any(case.currency != quote.base_currency for case in covered):
            reasons.append("호가 기준통화와 거래 통화가 일치하지 않습니다")
        if any(
            currency != quote.base_currency
            for currency in program.opening_balances
        ):
            reasons.append("현재 계산 엔진은 한 개 외화 프로그램만 지원합니다")
        if quote.counter_currency != "KRW":
            reasons.append("현재 계산 엔진은 원화 상대 호가만 지원합니다")
        if quote.settlement_date != max(
            case.expected_payment_date for case in covered
        ):
            reasons.append("호가 결제일과 순노출 분석 만기일이 일치하지 않습니다")

        net = sum(
            (
                case.amount
                if case.direction is TradeDirection.EXPORT
                else -case.amount
            )
            for case in covered
            if case.currency == quote.base_currency
        )
        if net == 0:
            reasons.append("순외화 노출이 없어 선물환 적용 대상이 없습니다")
        else:
            required_side = (
                HedgeQuoteSide.SELL if net > 0 else HedgeQuoteSide.BUY
            )
            if quote.side is not required_side:
                reasons.append("호가 매수·매도 방향이 순외화 노출과 반대입니다")
            if quote.notional < abs(net):
                reasons.append("호가 최대 명목금액이 순외화 노출보다 작습니다")
        return reasons

    @staticmethod
    def _descriptor(
        quote: UserForwardQuote,
        measure: HedgeMeasure,
    ) -> EvidenceDescriptor:
        return EvidenceDescriptor(
            evidence_id=f"hedge-quote:{quote.provider_id}:{quote.quote_id}",
            role=EvidenceRole.MARKET_DATA,
            identifiers=(
                quote.company_id,
                *quote.case_ids,
                measure.measure_id,
            ),
            source_ids=(quote.source_id,),
            generated_at=quote.quoted_at,
            payload={
                "attestation_kind": "company_specific_forward_quote",
                "source_class": "user_confirmed_provider_quote",
                "provider_id": quote.provider_id,
                "quote_id": quote.quote_id,
                "company_id": quote.company_id,
                "case_ids": quote.case_ids,
                "base_currency": quote.base_currency,
                "counter_currency": quote.counter_currency,
                "side": quote.side.value,
                "notional": str(quote.notional),
                "contract_rate": str(quote.contract_rate),
                "cost_rate": str(quote.cost_rate),
                "settlement_date": quote.settlement_date.isoformat(),
                "quoted_at": quote.quoted_at.isoformat(),
                "valid_until": quote.valid_until.isoformat(),
                "confirmed": True,
                "availability_status": measure.status.value,
                "limitations": (
                    "not_public_market_data",
                    "not_provider_verified",
                    "exact_program_scope_only",
                ),
            },
        )
