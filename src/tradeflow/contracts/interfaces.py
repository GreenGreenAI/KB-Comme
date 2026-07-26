from datetime import date
from typing import Any, Protocol

from tradeflow.domain.models import CurrencyExposure, RuleDecision, TradeProgram


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

