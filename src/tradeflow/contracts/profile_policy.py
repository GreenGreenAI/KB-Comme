"""Versioned contracts for deterministic profile classification and routing.

These contracts deliberately sit outside ``DecisionPacket``.  Segments may
change question order and presentation, but they are not evidence that a
customer is eligible for a financial product, limit, price, or approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"


class FactProvenance(StrEnum):
    VERIFIED = "verified"
    USER_DECLARED = "user_declared"
    ESTIMATED = "estimated"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    CONFLICTING = "conflicting"


@dataclass(frozen=True)
class ProfileFact:
    field: str
    value: Any
    provenance: FactProvenance
    evidence_id: str | None = None
    observed_at: str | None = None
    valid_until: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProfileFact":
        field_name = str(value.get("field") or "").strip()
        if not field_name:
            raise ValueError("profile fact requires field")
        provenance = FactProvenance(
            value.get("provenance", FactProvenance.USER_DECLARED.value)
        )
        evidence_id = value.get("evidence_id")
        if provenance in {
            FactProvenance.VERIFIED,
            FactProvenance.STALE,
            FactProvenance.CONFLICTING,
        } and not evidence_id:
            raise ValueError(
                f"{provenance.value} profile fact requires evidence_id"
            )
        return cls(
            field=field_name,
            value=value.get("value"),
            provenance=provenance,
            evidence_id=str(evidence_id) if evidence_id else None,
            observed_at=value.get("observed_at"),
            valid_until=value.get("valid_until"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "provenance": self.provenance.value,
            "evidence_id": self.evidence_id,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
        }


@dataclass(frozen=True)
class UserProfileFacts:
    """Normalized profile input plus field-level evidence records."""

    values: Mapping[str, Any]
    facts: tuple[ProfileFact, ...] = ()
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "UserProfileFacts":
        if not isinstance(value, Mapping):
            raise TypeError("user profile payload must be a mapping")
        facts_value = value.get("facts") or []
        if not isinstance(facts_value, list):
            raise TypeError("profile facts must be a list")
        facts = tuple(ProfileFact.from_mapping(item) for item in facts_value)
        values = {key: item for key, item in value.items() if key != "facts"}
        return cls(values=values, facts=facts)


@dataclass(frozen=True)
class SegmentMatch:
    type: str
    score: str
    evidence_ids: tuple[str, ...] = ()
    matched_facts: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "score": self.score,
            "evidence_ids": list(self.evidence_ids),
            "matched_facts": list(self.matched_facts),
            "missing_fields": list(self.missing_fields),
        }


@dataclass(frozen=True)
class SegmentClassification:
    axes: Mapping[str, tuple[str, ...]]
    primary_type: str | None
    secondary_types: tuple[str, ...]
    classifications: tuple[SegmentMatch, ...]
    missing_fields: tuple[str, ...] = ()
    fact_status: str = "available"
    used_provenance: str | None = None
    review_required: bool = False
    classifier_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "axes": {key: list(value) for key, value in self.axes.items()},
            "primary_type": self.primary_type,
            "secondary_types": list(self.secondary_types),
            "classifications": [item.as_dict() for item in self.classifications],
            "missing_fields": list(self.missing_fields),
            "fact_status": self.fact_status,
            "used_provenance": self.used_provenance,
            "review_required": self.review_required,
            "classifier_version": self.classifier_version,
        }


@dataclass(frozen=True)
class CapabilityRequest:
    capability_id: str
    reason: str
    required_consent: str | None = None
    required_inputs: tuple[str, ...] = ()
    fallback: str | None = None
    executable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "reason": self.reason,
            "required_consent": self.required_consent,
            "required_inputs": list(self.required_inputs),
            "fallback": self.fallback,
            "executable": self.executable,
        }


@dataclass(frozen=True)
class PolicyRoute:
    priority_views: tuple[str, ...]
    capabilities: tuple[CapabilityRequest, ...]
    authorized_capabilities: tuple[str, ...] = ()
    executed_capabilities: tuple[str, ...] = ()
    missing_consents: tuple[str, ...] = ()
    fallback: str | None = None
    decision_boundary: str = "classification_only"
    decision_status: str | None = None
    allowed_outputs: tuple[str, ...] = ()
    handoff_mode: str | None = None
    transmission_performed: bool = False
    claims: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        required_consents = tuple(
            dict.fromkeys(
                item.required_consent
                for item in self.capabilities
                if item.required_consent
            )
        )
        return {
            "priority_views": list(self.priority_views),
            "capabilities": [item.as_dict() for item in self.capabilities],
            "route_capabilities": [
                item.capability_id for item in self.capabilities
            ],
            "authorized_capabilities": list(self.authorized_capabilities),
            "executed_capabilities": list(self.executed_capabilities),
            "required_consents": list(required_consents),
            "missing_consents": list(self.missing_consents),
            "fallback": self.fallback,
            "decision_boundary": self.decision_boundary,
            "decision_status": self.decision_status,
            "allowed_outputs": list(self.allowed_outputs),
            "handoff_mode": self.handoff_mode,
            "transmission_performed": self.transmission_performed,
            "claims": list(self.claims),
        }


@dataclass(frozen=True)
class ProfilePolicyResult:
    profile: UserProfileFacts
    classification: SegmentClassification
    route: PolicyRoute
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "profile_facts": [item.as_dict() for item in self.profile.facts],
        }
        result.update(self.classification.as_dict())
        result.update(self.route.as_dict())
        return result
