"""Typed operational evidence for company and K-SURE eligibility facts.

Provider responses are not facts by themselves.  This module validates their
identity, source, time bounds and catalog fields, then emits the exact
``FactAssertion`` and ``EvidenceDescriptor`` objects consumed by the rule
pipeline.  Conflicting fresh sources are never resolved by an implicit source
priority; they require review or an explicit upstream correction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import EvidenceRole, EvidenceSubjectKind
from tradeflow.domain.models import TradeProgram
from tradeflow.domain.snapshot import require_aware
from tradeflow.knowledge.facts import (
    FactAssertion,
    FactCatalog,
    FactContractError,
)


_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


class KsureCreditSubject(StrEnum):
    EXPORTER = "exporter"
    IMPORTER = "importer"


@dataclass(frozen=True)
class EvidenceMetadata:
    """Immutable provenance attached to one provider record."""

    evidence_id: str
    source_id: str
    observed_at: datetime
    retrieved_at: datetime
    valid_until: datetime | None
    content_hash: str

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("evidence_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        observed_at = require_aware(self.observed_at, "observed_at")
        retrieved_at = require_aware(self.retrieved_at, "retrieved_at")
        if retrieved_at < observed_at:
            raise ValueError("retrieved_at must not precede observed_at")
        if self.valid_until is not None:
            valid_until = require_aware(self.valid_until, "valid_until")
            if valid_until < observed_at:
                raise ValueError("valid_until must not precede observed_at")
        if not _SHA256.fullmatch(self.content_hash):
            raise ValueError("content_hash must be canonical sha256:<64 lowercase hex>")


@dataclass(frozen=True)
class EligibilityEvidenceRecord:
    """Provider-neutral claims for one company or one trade case."""

    metadata: EvidenceMetadata
    subject_kind: EvidenceSubjectKind
    subject_id: str
    company_id: str
    facts: Mapping[str, Any]
    provider_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, EvidenceMetadata):
            raise TypeError("metadata must be EvidenceMetadata")
        if not isinstance(self.subject_kind, EvidenceSubjectKind):
            raise TypeError("subject_kind must be EvidenceSubjectKind")
        if not self.subject_id:
            raise ValueError("subject_id is required")
        if not self.company_id:
            raise ValueError("company_id is required")
        if (
            self.subject_kind is EvidenceSubjectKind.COMPANY
            and self.subject_id != self.company_id
        ):
            raise ValueError("company evidence subject_id must equal company_id")
        if not self.provider_key:
            raise ValueError("provider_key is required")
        if not isinstance(self.facts, Mapping) or not self.facts:
            raise ValueError("eligibility evidence must contain at least one fact")
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


@dataclass(frozen=True)
class CompanyQualificationEvidence:
    """Official or attested company qualification fields.

    Values remain optional because a source may attest only one qualification.
    Missing values are omitted rather than guessed.
    """

    metadata: EvidenceMetadata
    company_id: str
    provider_key: str
    is_sme: bool | None = None
    company_size: str | None = None
    credit_issue_free: bool | None = None

    def to_record(self) -> EligibilityEvidenceRecord:
        facts = {
            field: value
            for field, value in (
                ("company.is_sme", self.is_sme),
                ("company.size", self.company_size),
                ("company.credit_issue_free", self.credit_issue_free),
            )
            if value is not None
        }
        return EligibilityEvidenceRecord(
            metadata=self.metadata,
            subject_kind=EvidenceSubjectKind.COMPANY,
            subject_id=self.company_id,
            company_id=self.company_id,
            facts=facts,
            provider_key=self.provider_key,
        )


@dataclass(frozen=True)
class KsureCreditEvidence:
    """One K-SURE exporter or importer grade bound to its real subject."""

    metadata: EvidenceMetadata
    subject: KsureCreditSubject
    subject_id: str
    company_id: str
    grade: str
    provider_key: str

    def to_record(self) -> EligibilityEvidenceRecord:
        if not isinstance(self.subject, KsureCreditSubject):
            raise TypeError("subject must be KsureCreditSubject")
        is_exporter = self.subject is KsureCreditSubject.EXPORTER
        return EligibilityEvidenceRecord(
            metadata=self.metadata,
            subject_kind=(
                EvidenceSubjectKind.COMPANY
                if is_exporter
                else EvidenceSubjectKind.CASE
            ),
            subject_id=self.subject_id,
            company_id=self.company_id,
            facts={
                (
                    "company.ksure_exporter_grade"
                    if is_exporter
                    else "counterparty.ksure_importer_grade"
                ): self.grade
            },
            provider_key=self.provider_key,
        )


class EligibilityEvidenceProvider(Protocol):
    """Adapter contract for official APIs, verified files or attestations."""

    provider_key: str

    def collect(
        self,
        *,
        program: TradeProgram,
        evaluated_at: datetime,
    ) -> tuple[EligibilityEvidenceRecord, ...]: ...


class EligibilityProviderRegistry:
    """Object registry that makes provider selection explicit and testable."""

    def __init__(self) -> None:
        self._providers: dict[str, EligibilityEvidenceProvider] = {}

    def register(self, provider: EligibilityEvidenceProvider) -> None:
        key = getattr(provider, "provider_key", None)
        if not key:
            raise ValueError("provider_key is required")
        if key in self._providers:
            raise ValueError(f"duplicate eligibility provider_key: {key}")
        self._providers[key] = provider

    def collect(
        self,
        *,
        program: TradeProgram,
        evaluated_at: datetime,
    ) -> tuple[EligibilityEvidenceRecord, ...]:
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        records: list[EligibilityEvidenceRecord] = []
        evidence_ids: set[str] = set()
        for key, provider in self._providers.items():
            provided = tuple(
                provider.collect(program=program, evaluated_at=evaluated_at)
            )
            for record in provided:
                if record.provider_key != key:
                    raise FactContractError(
                        f"{record.metadata.evidence_id}: provider_key "
                        f"{record.provider_key!r} does not match registry key {key!r}"
                    )
                if record.metadata.evidence_id in evidence_ids:
                    raise FactContractError(
                        f"duplicate evidence_id: {record.metadata.evidence_id}"
                    )
                evidence_ids.add(record.metadata.evidence_id)
                records.append(record)
        return tuple(records)

    @property
    def providers(self) -> Mapping[str, EligibilityEvidenceProvider]:
        return MappingProxyType(self._providers)


@dataclass(frozen=True)
class EligibilityFactInput:
    assertions_by_case: Mapping[str, tuple[FactAssertion, ...]]
    evidence: tuple[EvidenceDescriptor, ...]
    missing_fields_by_case: Mapping[str, tuple[str, ...]]
    stale_evidence_ids: tuple[str, ...] = ()
    unusable_evidence: tuple[EvidenceDescriptor, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assertions_by_case",
            MappingProxyType(dict(self.assertions_by_case)),
        )
        object.__setattr__(
            self,
            "missing_fields_by_case",
            MappingProxyType(dict(self.missing_fields_by_case)),
        )


class EligibilityEvidenceAssembler:
    """Normalize fresh trusted records into case-scoped fact input."""

    def __init__(
        self,
        catalog: FactCatalog,
        *,
        trusted_source_ids: Iterable[str],
    ) -> None:
        trusted = frozenset(trusted_source_ids)
        if not trusted or any(not item for item in trusted):
            raise ValueError("trusted_source_ids must contain at least one source")
        self.catalog = catalog
        self.trusted_source_ids = trusted

    def assemble(
        self,
        *,
        program: TradeProgram,
        records: Iterable[EligibilityEvidenceRecord],
        evaluated_at: datetime,
        required_fields_by_case: Mapping[str, Iterable[str]] | None = None,
    ) -> EligibilityFactInput:
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        records = tuple(records)
        evidence_ids = [record.metadata.evidence_id for record in records]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise FactContractError("eligibility evidence contains duplicate evidence_id values")

        cases_by_id = {case.case_id: case for case in program.cases}
        claims_by_case: dict[str, dict[str, tuple[Any, list[str]]]] = {
            case_id: {} for case_id in cases_by_id
        }
        descriptors: list[EvidenceDescriptor] = []
        unusable_descriptors: list[EvidenceDescriptor] = []
        stale_ids: list[str] = []

        for record in records:
            if not isinstance(record, EligibilityEvidenceRecord):
                raise TypeError("records must contain EligibilityEvidenceRecord values")
            metadata = record.metadata
            if metadata.source_id not in self.trusted_source_ids:
                raise FactContractError(
                    f"{metadata.evidence_id}: untrusted source_id {metadata.source_id}"
                )
            if metadata.observed_at > evaluated_at or metadata.retrieved_at > evaluated_at:
                raise FactContractError(
                    f"{metadata.evidence_id}: evidence timestamp is in the future"
                )
            target_case_ids = self._target_cases(record, program, cases_by_id)
            normalized_facts = self._normalize_facts(record)
            if metadata.valid_until is not None and evaluated_at > metadata.valid_until:
                stale_ids.append(metadata.evidence_id)
                unusable_descriptors.append(
                    self._descriptor(
                        record,
                        target_case_ids,
                        normalized_facts,
                        usable=False,
                    )
                )
                continue

            descriptors.append(
                self._descriptor(
                    record,
                    target_case_ids,
                    normalized_facts,
                    usable=True,
                )
            )
            for case_id in target_case_ids:
                case_claims = claims_by_case[case_id]
                for field, value in normalized_facts.items():
                    existing = case_claims.get(field)
                    if existing is None:
                        case_claims[field] = (value, [metadata.evidence_id])
                    elif existing[0] != value:
                        raise FactContractError(
                            f"{case_id}:{field}: conflicting fresh evidence "
                            f"{existing[0]!r} != {value!r}"
                        )
                    else:
                        existing[1].append(metadata.evidence_id)

        required = self._normalize_required_fields(
            cases_by_id,
            required_fields_by_case or {},
        )
        assertions_by_case: dict[str, tuple[FactAssertion, ...]] = {}
        missing_by_case: dict[str, tuple[str, ...]] = {}
        for case_id, claims in claims_by_case.items():
            assertions_by_case[case_id] = tuple(
                FactAssertion(field, value, tuple(ids))
                for field, (value, ids) in sorted(claims.items())
            )
            missing_by_case[case_id] = tuple(
                field for field in required[case_id] if field not in claims
            )

        return EligibilityFactInput(
            assertions_by_case=assertions_by_case,
            evidence=tuple(descriptors),
            missing_fields_by_case=missing_by_case,
            stale_evidence_ids=tuple(stale_ids),
            unusable_evidence=tuple(unusable_descriptors),
        )

    @staticmethod
    def _descriptor(
        record: EligibilityEvidenceRecord,
        target_case_ids: tuple[str, ...],
        normalized_facts: Mapping[str, Any],
        *,
        usable: bool,
    ) -> EvidenceDescriptor:
        metadata = record.metadata
        identifiers = tuple(dict.fromkeys((record.subject_id, *target_case_ids)))
        payload = {
            "provider_key": record.provider_key,
            "subject_kind": record.subject_kind.value,
            "subject_id": record.subject_id,
            "company_id": record.company_id,
            "observed_at": metadata.observed_at.isoformat(),
            "retrieved_at": metadata.retrieved_at.isoformat(),
            "valid_until": (
                metadata.valid_until.isoformat()
                if metadata.valid_until is not None
                else None
            ),
            "content_hash": metadata.content_hash,
            "usability": "active" if usable else "stale",
        }
        if usable:
            payload["facts"] = dict(normalized_facts)
        else:
            payload["rejected_facts"] = dict(normalized_facts)
        return EvidenceDescriptor(
            evidence_id=metadata.evidence_id,
            role=EvidenceRole.SUPPORT_ELIGIBILITY,
            identifiers=identifiers,
            source_ids=(metadata.source_id,),
            generated_at=metadata.retrieved_at,
            payload=payload,
        )

    def _target_cases(
        self,
        record: EligibilityEvidenceRecord,
        program: TradeProgram,
        cases_by_id: Mapping[str, Any],
    ) -> tuple[str, ...]:
        if record.company_id != program.company.company_id:
            raise FactContractError(
                f"{record.metadata.evidence_id}: evidence company does not match program"
            )
        if record.subject_kind is EvidenceSubjectKind.COMPANY:
            return tuple(cases_by_id)
        if record.subject_id not in cases_by_id:
            raise FactContractError(
                f"{record.metadata.evidence_id}: unknown case subject {record.subject_id}"
            )
        return (record.subject_id,)

    def _normalize_facts(
        self,
        record: EligibilityEvidenceRecord,
    ) -> Mapping[str, Any]:
        normalized: dict[str, Any] = {}
        for field, value in record.facts.items():
            definition = self.catalog.definitions.get(field)
            if definition is None:
                raise FactContractError(f"unknown fact: {field}")
            if definition.evidence_role is not EvidenceRole.SUPPORT_ELIGIBILITY:
                raise FactContractError(
                    f"{field}: eligibility provider cannot attest "
                    f"{definition.evidence_role.value} fact"
                )
            normalized[field] = self.catalog.normalize(field, value)
        return MappingProxyType(normalized)

    def _normalize_required_fields(
        self,
        cases_by_id: Mapping[str, Any],
        required_fields_by_case: Mapping[str, Iterable[str]],
    ) -> dict[str, tuple[str, ...]]:
        unknown_cases = set(required_fields_by_case) - set(cases_by_id)
        if unknown_cases:
            raise FactContractError(
                "required fields reference unknown cases: "
                + ", ".join(sorted(unknown_cases))
            )
        result: dict[str, tuple[str, ...]] = {}
        for case_id in cases_by_id:
            fields = tuple(dict.fromkeys(required_fields_by_case.get(case_id, ())))
            for field in fields:
                definition = self.catalog.definitions.get(field)
                if definition is None:
                    raise FactContractError(f"unknown fact: {field}")
                if definition.evidence_role is not EvidenceRole.SUPPORT_ELIGIBILITY:
                    raise FactContractError(
                        f"{field}: required eligibility fact has role "
                        f"{definition.evidence_role.value}"
                    )
            result[case_id] = fields
        return result
