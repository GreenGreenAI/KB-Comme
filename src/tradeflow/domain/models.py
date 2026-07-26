from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from tradeflow.domain.enums import (
    DecisionStatus,
    InstrumentKind,
    PaymentMethod,
    TradeDirection,
)


def money(value: Decimal | str | int | float) -> Decimal:
    """Convert external numeric input without introducing binary float noise."""
    return Decimal(str(value))


@dataclass(frozen=True)
class CompanyProfile:
    company_id: str
    name: str
    country_code: str = "KR"
    is_sme: bool | None = None
    annual_export_usd: Decimal | None = None
    industry_code: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def facts(self) -> dict[str, Any]:
        values = {
            "company.country_code": self.country_code,
            "company.is_sme": self.is_sme,
            "company.annual_export_usd": self.annual_export_usd,
            "company.industry_code": self.industry_code,
        }
        values.update(self.attributes)
        return values


@dataclass(frozen=True)
class TradeCase:
    case_id: str
    direction: TradeDirection
    currency: str
    amount: Decimal
    expected_payment_date: date
    payment_method: PaymentMethod
    counterparty_country: str | None = None
    confirmed: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("trade amount must be positive")
        object.__setattr__(self, "currency", self.currency.upper())

    def facts(self) -> dict[str, Any]:
        values = {
            "trade.direction": self.direction.value,
            "trade.currency": self.currency,
            "trade.amount": self.amount,
            "trade.payment_method": self.payment_method.value,
            "trade.counterparty_country": self.counterparty_country,
        }
        values.update(self.attributes)
        return values


@dataclass(frozen=True)
class TradeProgram:
    program_id: str
    company: CompanyProfile
    cases: tuple[TradeCase, ...]
    opening_balances: dict[str, Decimal] = field(default_factory=dict)
    as_of: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("at least one trade case is required")
        normalized = {key.upper(): money(value) for key, value in self.opening_balances.items()}
        object.__setattr__(self, "opening_balances", normalized)


@dataclass(frozen=True)
class CashflowPoint:
    event_date: date
    case_id: str
    currency: str
    inflow: Decimal
    outflow: Decimal
    running_balance: Decimal
    funding_gap: Decimal


@dataclass(frozen=True)
class CurrencyExposure:
    """Currency-level exposure.

    `economic_offset` is the whole-horizon offset between receipts and payments.
    `maturity_matched_amount` is the part of it that is actually settled by an
    earlier receipt, so the two together show how much of the offset is real at
    the time the payment falls due. `trade_net_exposure` keeps its sign: a
    negative value means payments exceed receipts, and the hedge payoff formula
    depends on that direction.
    """

    currency: str
    opening_balance: Decimal
    total_inflow: Decimal
    total_outflow: Decimal
    economic_offset: Decimal
    maturity_matched_amount: Decimal
    trade_net_exposure: Decimal
    ending_balance: Decimal
    peak_funding_gap: Decimal
    timeline: tuple[CashflowPoint, ...]


@dataclass(frozen=True)
class HedgeInstrument:
    """A hedging instrument together with whether this company may use it.

    Availability is decided by the knowledge layer from collateral and credit
    facts, never by the optimizer. An instrument the company cannot access must
    still be returned, carrying the reason it was excluded, so the answer says
    why something is unavailable instead of quietly dropping it.
    """

    instrument_id: str
    kind: InstrumentKind
    available: bool
    exclusion_reasons: tuple[str, ...] = ()
    contract_rate: Decimal | None = None
    cost_rate: Decimal = Decimal("0")
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.available and not self.exclusion_reasons:
            raise ValueError(
                f"{self.instrument_id}: an unavailable instrument must carry "
                "at least one exclusion reason"
            )
        if self.available and self.exclusion_reasons:
            raise ValueError(
                f"{self.instrument_id}: an available instrument must not carry "
                "exclusion reasons"
            )
        if self.cost_rate < 0:
            raise ValueError(f"{self.instrument_id}: cost_rate must not be negative")


@dataclass(frozen=True)
class RuleDecision:
    rule_id: str
    title: str
    status: DecisionStatus
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnalysisResult:
    program_id: str
    exposures: tuple[CurrencyExposure, ...]
    decisions: tuple[RuleDecision, ...]
    evidence: tuple[Any, ...]
    evidence_coverage: dict[str, Any]
    review_required: bool
    review_reasons: tuple[str, ...]

