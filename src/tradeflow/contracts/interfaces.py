from datetime import date
from typing import Any, Protocol

from tradeflow.domain.models import (
    CurrencyExposure,
    HedgeInstrument,
    RuleDecision,
    TradeProgram,
)


class ExposureService(Protocol):
    """Contract owned jointly; implemented by the platform owner."""

    def analyze(self, program: TradeProgram) -> tuple[CurrencyExposure, ...]: ...


class KnowledgeService(Protocol):
    """Contract owned jointly; implemented by the knowledge owner."""

    def evaluate(
        self,
        *,
        topic: str,
        facts: dict[str, Any],
        as_of: date,
    ) -> tuple[RuleDecision, ...]: ...

    def procedure_for(self, rule_id: str) -> dict[str, Any] | None: ...


class InstrumentAvailabilityService(Protocol):
    """Contract owned jointly; implemented by the knowledge owner.

    Decides which hedging instruments a company may actually use, from its
    collateral and credit facts. Returns every candidate, including the ones it
    rules out, so the caller can report exclusion reasons.
    """

    def available_instruments(
        self,
        *,
        program: TradeProgram,
        as_of: date,
    ) -> tuple[HedgeInstrument, ...]: ...

