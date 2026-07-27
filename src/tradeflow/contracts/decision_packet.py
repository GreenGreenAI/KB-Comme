"""Immutable hand-off contract from deterministic engines to an LLM.

An LLM may explain a DecisionPacket, but it must not recalculate figures,
change decision states, invent evidence, or weaken a review requirement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import DecisionStatus, EvidenceRole
from tradeflow.domain.models import AnalysisResult, CurrencyExposure, RuleDecision


@dataclass(frozen=True)
class DecisionInput:
    name: str
    value: Any


@dataclass(frozen=True)
class NumericClaim:
    path: str
    value: Decimal


@dataclass(frozen=True)
class DecisionStatusClaim:
    rule_id: str
    status: DecisionStatus
    subject_id: str | None = None


@dataclass(frozen=True)
class PacketRequirement:
    field: str
    operator: str
    expected_value: Any
    description: str
    current_value: Any


@dataclass(frozen=True)
class PacketDecision:
    rule_id: str
    title: str
    status: DecisionStatus
    reasons: tuple[str, ...]
    missing_fields: tuple[str, ...]
    source_ids: tuple[str, ...]
    requirements: tuple[PacketRequirement, ...]
    source_claim_ids: tuple[str, ...]
    candidate_outcome: tuple[tuple[str, Any], ...]
    subject_id: str | None


@dataclass(frozen=True)
class PacketEvidence:
    evidence_id: str
    role: EvidenceRole
    identifiers: tuple[str, ...]
    source_ids: tuple[str, ...]
    generated_at: datetime
    payload: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class DecisionPacket:
    """Versioned, deterministic input to the synthesis layer."""

    packet_id: str
    schema_version: str
    program_id: str
    as_of: date
    inputs: tuple[DecisionInput, ...]
    exposures: tuple[CurrencyExposure, ...]
    decisions: tuple[PacketDecision, ...]
    evidence: tuple[PacketEvidence, ...]
    review_required: bool
    review_reasons: tuple[str, ...]

    @classmethod
    def from_analysis(
        cls,
        result: AnalysisResult,
        *,
        as_of: date,
        inputs: Mapping[str, Any],
    ) -> DecisionPacket:
        fingerprint = _identity_fingerprint(
            {
                "as_of": as_of,
                "inputs": inputs,
                "analysis": result,
            }
        )
        return cls(
            packet_id=(
                f"decision:{result.program_id}:{as_of.isoformat()}:{fingerprint[:16]}"
            ),
            schema_version="1.1",
            program_id=result.program_id,
            as_of=as_of,
            inputs=tuple(
                DecisionInput(name, _freeze(value))
                for name, value in sorted(inputs.items())
            ),
            exposures=result.exposures,
            decisions=tuple(_freeze_decision(item) for item in result.decisions),
            evidence=tuple(_freeze_evidence(item) for item in result.evidence),
            review_required=result.review_required,
            review_reasons=result.review_reasons,
        )

    def numeric_claims(self) -> dict[str, Decimal]:
        """Return the only numeric claims a synthesis result may make."""
        claims: dict[str, Decimal] = {}
        for exposure in self.exposures:
            prefix = f"exposures.{exposure.currency}"
            claims.update(
                {
                    f"{prefix}.opening_balance": exposure.opening_balance,
                    f"{prefix}.total_inflow": exposure.total_inflow,
                    f"{prefix}.total_outflow": exposure.total_outflow,
                    f"{prefix}.economic_offset": exposure.economic_offset,
                    f"{prefix}.maturity_matched_amount": (
                        exposure.maturity_matched_amount
                    ),
                    f"{prefix}.trade_net_exposure": exposure.trade_net_exposure,
                    f"{prefix}.ending_balance": exposure.ending_balance,
                    f"{prefix}.peak_funding_gap": exposure.peak_funding_gap,
                }
            )
        return claims


@dataclass(frozen=True)
class SynthesisResult:
    """Structured LLM output accompanied by non-authoritative prose."""

    packet_id: str
    narrative: str
    decision_statuses: tuple[DecisionStatusClaim, ...]
    numeric_claims: tuple[NumericClaim, ...]
    evidence_ids: tuple[str, ...]
    review_required: bool
    review_reasons: tuple[str, ...]


def validate_synthesis(
    packet: DecisionPacket,
    result: SynthesisResult,
) -> tuple[str, ...]:
    """Reject synthesis that changes or invents deterministic conclusions."""
    errors: list[str] = []

    if result.packet_id != packet.packet_id:
        errors.append("packet_id does not match")

    expected_decisions = {
        (decision.subject_id, decision.rule_id): decision.status
        for decision in packet.decisions
    }
    actual_decisions = {
        (claim.subject_id, claim.rule_id): claim.status
        for claim in result.decision_statuses
    }
    if len(actual_decisions) != len(result.decision_statuses):
        errors.append("decision_statuses contains duplicate rule_id values")
    if actual_decisions != expected_decisions:
        errors.append("decision statuses must exactly match the packet")

    allowed_numbers = packet.numeric_claims()
    seen_paths: set[str] = set()
    for claim in result.numeric_claims:
        if claim.path in seen_paths:
            errors.append(f"numeric claim is duplicated: {claim.path}")
            continue
        seen_paths.add(claim.path)
        if claim.path not in allowed_numbers:
            errors.append(f"numeric claim is not in the packet: {claim.path}")
        elif claim.value != allowed_numbers[claim.path]:
            errors.append(f"numeric claim changed packet value: {claim.path}")

    allowed_evidence = {item.evidence_id for item in packet.evidence}
    if len(set(result.evidence_ids)) != len(result.evidence_ids):
        errors.append("evidence_ids contains duplicates")
    invented_evidence = set(result.evidence_ids) - allowed_evidence
    if invented_evidence:
        errors.append(
            "unknown evidence_ids: " + ", ".join(sorted(invented_evidence))
        )

    if result.review_required != packet.review_required:
        errors.append("review_required must exactly match the packet")
    if result.review_reasons != packet.review_reasons:
        errors.append("review_reasons must exactly match the packet")

    return tuple(errors)


def _freeze(value: Any) -> Any:
    """Recursively make common external input containers immutable."""
    if isinstance(value, Mapping):
        return tuple((key, _freeze(item)) for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze(item) for item in value))
    return value


def _identity_fingerprint(value: Any) -> str:
    canonical = json.dumps(
        _identity_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _identity_value(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _identity_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _identity_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_identity_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_identity_value(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (date, datetime)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot fingerprint {type(value).__name__}")


def _freeze_decision(decision: RuleDecision) -> PacketDecision:
    return PacketDecision(
        rule_id=decision.rule_id,
        title=decision.title,
        status=decision.status,
        reasons=decision.reasons,
        missing_fields=decision.missing_fields,
        source_ids=decision.source_ids,
        requirements=tuple(
            PacketRequirement(
                field=item.field,
                operator=item.operator,
                expected_value=_freeze(item.expected_value),
                description=item.description,
                current_value=_freeze(item.current_value),
            )
            for item in decision.requirements
        ),
        source_claim_ids=decision.source_claim_ids,
        candidate_outcome=_freeze(decision.candidate_outcome),
        subject_id=decision.subject_id,
    )


def _freeze_evidence(evidence: EvidenceDescriptor) -> PacketEvidence:
    return PacketEvidence(
        evidence_id=evidence.evidence_id,
        role=evidence.role,
        identifiers=evidence.identifiers,
        source_ids=evidence.source_ids,
        generated_at=evidence.generated_at,
        payload=tuple(
            (key, _freeze(value)) for key, value in sorted(evidence.payload.items())
        ),
    )
