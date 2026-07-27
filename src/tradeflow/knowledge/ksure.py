"""Typed, evidence-referenced inputs for K-SURE case evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.datasets import KsureCountryPolicyCatalog, SnapshotDataset
from tradeflow.domain.enums import EvidenceRole
from tradeflow.domain.models import TradeCase
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


def bind_country_policy(
    profile: KsureCaseProfile,
    dataset: SnapshotDataset,
    case: TradeCase,
) -> tuple[KsureCaseProfile, EvidenceDescriptor]:
    """Bind a verified country-policy snapshot to one K-SURE case profile."""
    if not isinstance(dataset.value, KsureCountryPolicyCatalog):
        raise TypeError("dataset is not a K-SURE country-policy catalog")
    if profile.country_restricted is not None:
        raise FactContractError(
            "counterparty.country_restricted is already set and cannot be overridden"
        )
    country_code = case.counterparty_country
    if country_code is None:
        raise FactContractError(
            f"{case.case_id}: counterparty country is required for K-SURE policy"
        )
    try:
        policy = dataset.value.get(country_code)
        country_restricted = policy.country_restricted
    except (KeyError, ValueError) as exc:
        raise FactContractError(str(exc)) from None

    evidence_id = (
        f"ksure-country-policy:{case.case_id}:{policy.country_code}:"
        f"{dataset.ref.version}"
    )
    evidence = EvidenceDescriptor(
        evidence_id=evidence_id,
        role=EvidenceRole.SUPPORT_ELIGIBILITY,
        identifiers=(case.case_id, policy.country_code),
        source_ids=(dataset.ref.source_id,),
        generated_at=dataset.ref.retrieved_at,
        payload={
            "facts": {
                "counterparty.country_restricted": country_restricted,
            },
            "country_code": policy.country_code,
            "country_name": policy.country_name,
            "policy_status": policy.status.value,
            "deep_watch": policy.deep_watch,
            "snapshot": {
                "source_id": dataset.ref.source_id,
                "version": dataset.ref.version,
                "content_hash": dataset.ref.content_hash,
                "observed_at": dataset.ref.observed_at.isoformat(),
            },
        },
    )
    evidence_ids = dict(profile.evidence_ids_by_field)
    if "counterparty.country_restricted" in evidence_ids:
        raise FactContractError(
            "counterparty.country_restricted evidence is already configured"
        )
    evidence_ids["counterparty.country_restricted"] = (evidence_id,)
    return (
        replace(
            profile,
            country_restricted=country_restricted,
            evidence_ids_by_field=evidence_ids,
        ),
        evidence,
    )
