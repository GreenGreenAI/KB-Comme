from datetime import date
from typing import Any, Mapping, Protocol

from tradeflow.domain.enums import Freshness
from tradeflow.domain.models import (
    CurrencyExposure,
    HedgeMeasure,
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
        source_freshness: Mapping[str, Freshness] | None = None,
    ) -> tuple[RuleDecision, ...]: ...

    def procedure_for(self, rule_id: str) -> dict[str, Any] | None: ...


class HedgeMeasureAvailabilityService(Protocol):
    """Contract owned jointly; implemented by the knowledge owner.

    Judges which hedging measures a company may use, from its collateral and
    credit facts. Returns every candidate with its status, including the ones
    ruled out and the ones still undetermined, so the caller can report reasons
    rather than infer them from an absence.
    """

    def evaluate_measures(
        self,
        *,
        program: TradeProgram,
        as_of: date,
    ) -> tuple[HedgeMeasure, ...]: ...

