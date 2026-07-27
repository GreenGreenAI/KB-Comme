"""Typed, evidence-referenced inputs for K-SURE case evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.knowledge.facts import FactAssertion, FactContractError


_FIELD_BY_ATTRIBUTE = {
    "company_size": "company.size",
    "credit_issue_free": "company.credit_issue_free",
    "exporter_grade": "company.ksure_exporter_grade",
    "importer_grade": "counterparty.ksure_importer_grade",
    "country_restricted": "counterparty.country_restricted",
    "payment_term_days": "trade.payment_term_days",
    "financing_purpose": "financing.purpose",
    "has_bank_consultation": "financing.has_bank_consultation",
}


@dataclass(frozen=True)
class KsureCaseProfile:
    company_size: str | None = None
    credit_issue_free: bool | None = None
    exporter_grade: str | None = None
    importer_grade: str | None = None
    country_restricted: bool | None = None
    payment_term_days: int | None = None
    financing_purpose: str | None = None
    has_bank_consultation: bool | None = None
    evidence_ids_by_field: Mapping[str, tuple[str, ...]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if self.payment_term_days is not None and self.payment_term_days < 0:
            raise ValueError("payment_term_days must be non-negative")
        unknown = set(self.evidence_ids_by_field) - set(_FIELD_BY_ATTRIBUTE.values())
        if unknown:
            raise FactContractError(
                "unknown K-SURE evidence fields: " + ", ".join(sorted(unknown))
            )
        object.__setattr__(
            self,
            "evidence_ids_by_field",
            MappingProxyType(
                {
                    key: tuple(value)
                    for key, value in self.evidence_ids_by_field.items()
                }
            ),
        )

    def assertions(self) -> tuple[FactAssertion, ...]:
        assertions: list[FactAssertion] = []
        for attribute, fact_field in _FIELD_BY_ATTRIBUTE.items():
            value: Any = getattr(self, attribute)
            if value is None:
                continue
            evidence_ids = self.evidence_ids_by_field.get(fact_field)
            if not evidence_ids:
                raise FactContractError(
                    f"{fact_field}: K-SURE profile requires evidence_ids"
                )
            assertions.append(FactAssertion(fact_field, value, evidence_ids))
        return tuple(assertions)
