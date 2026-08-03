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
from typing import Any, Mapping, Protocol

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import (
    DecisionCategory,
    DecisionStatus,
    DocumentRequirementKind,
    EvidenceRole,
)
from tradeflow.domain.models import (
    AnalysisResult,
    CurrencyExposure,
    RecommendedAction,
    RuleDecision,
)


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
class HedgeModelClaim:
    model_id: str
    model_version: str
    is_champion: bool
    status: str


@dataclass(frozen=True)
class PacketRequirement:
    field: str
    operator: str
    expected_value: Any
    description: str
    current_value: Any


@dataclass(frozen=True)
class PacketCheck:
    """One condition of a rule, in the rule's own words."""

    field: str
    description: str
    status: str


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
    matched: bool | None
    categories: tuple[DecisionCategory, ...]
    checks: tuple[PacketCheck, ...] = ()


@dataclass(frozen=True)
class PacketDocument:
    document_id: str
    title: str


@dataclass(frozen=True)
class PacketDocumentRequirement:
    requirement_id: str
    kind: DocumentRequirementKind
    documents: tuple[PacketDocument, ...]
    condition_description: str | None
    selector_field: str | None


@dataclass(frozen=True)
class PacketAction:
    subject_id: str | None
    rule_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    authority: str | None
    action: str
    timing: str | None
    deadline: date | None
    requirements: tuple[PacketRequirement, ...]
    required_documents: tuple[str, ...]
    document_set_ids: tuple[str, ...]
    document_requirements: tuple[PacketDocumentRequirement, ...]
    steps: tuple[str, ...]
    source_ids: tuple[str, ...]
    source_claim_ids: tuple[str, ...]


@dataclass(frozen=True)
class PacketEvidence:
    evidence_id: str
    role: EvidenceRole
    identifiers: tuple[str, ...]
    source_ids: tuple[str, ...]
    generated_at: datetime
    payload: tuple[tuple[str, Any], ...]


class HedgeDecisionInput(Protocol):
    """Structural hand-off from a deterministic hedge model."""

    model_id: str
    model_version: str
    objective: str
    recommended_ratio: Decimal
    sufficient: bool
    status: str
    adverse_rate: Decimal
    forecast_lower: Decimal
    forecast_upper: Decimal
    breach_probability: float
    expected_shortfall: Decimal
    estimated_cost: Decimal
    scenario_count: int
    parameters: Mapping[str, Any]


@dataclass(frozen=True)
class PacketHedgeDecision:
    model_id: str
    model_version: str
    objective: str
    is_champion: bool
    recommended_ratio: Decimal
    sufficient: bool
    status: str
    adverse_rate: Decimal
    forecast_lower: Decimal
    forecast_upper: Decimal
    breach_probability: Decimal
    expected_shortfall: Decimal
    estimated_cost: Decimal
    scenario_count: int
    parameters: tuple[tuple[str, Any], ...]


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
    actions: tuple[PacketAction, ...]
    evidence: tuple[PacketEvidence, ...]
    hedge_decisions: tuple[PacketHedgeDecision, ...]
    review_required: bool
    review_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        model_ids = [item.model_id for item in self.hedge_decisions]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("hedge_decisions must have unique model_id values")
        champion_count = sum(item.is_champion for item in self.hedge_decisions)
        if self.hedge_decisions and champion_count != 1:
            raise ValueError(
                "hedge_decisions must identify exactly one champion"
            )

    @classmethod
    def from_analysis(
        cls,
        result: AnalysisResult,
        *,
        as_of: date,
        inputs: Mapping[str, Any],
        hedge_decisions: tuple[HedgeDecisionInput, ...] = (),
        champion_model_id: str | None = None,
    ) -> DecisionPacket:
        hedge_decisions = tuple(hedge_decisions)
        model_ids = [item.model_id for item in hedge_decisions]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("hedge decision model IDs must be unique")
        if hedge_decisions:
            if champion_model_id not in set(model_ids):
                raise ValueError(
                    "champion_model_id must identify a supplied hedge decision"
                )
        elif champion_model_id is not None:
            raise ValueError(
                "champion_model_id requires at least one hedge decision"
            )
        fingerprint = _identity_fingerprint(
            {
                "as_of": as_of,
                "inputs": inputs,
                "analysis": result,
                "hedge_decisions": hedge_decisions,
                "champion_model_id": champion_model_id,
            }
        )
        return cls(
            packet_id=(
                f"decision:{result.program_id}:{as_of.isoformat()}:{fingerprint[:16]}"
            ),
            schema_version="1.6",
            program_id=result.program_id,
            as_of=as_of,
            inputs=tuple(
                DecisionInput(name, _freeze(value))
                for name, value in sorted(inputs.items())
            ),
            exposures=result.exposures,
            decisions=tuple(_freeze_decision(item) for item in result.decisions),
            actions=tuple(_freeze_action(item) for item in result.actions),
            evidence=tuple(_freeze_evidence(item) for item in result.evidence),
            hedge_decisions=tuple(
                _freeze_hedge_decision(
                    item,
                    is_champion=item.model_id == champion_model_id,
                )
                for item in hedge_decisions
            ),
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
        for decision in self.hedge_decisions:
            prefix = f"hedge_decisions.{decision.model_id}"
            claims.update(
                {
                    f"{prefix}.recommended_ratio": decision.recommended_ratio,
                    f"{prefix}.adverse_rate": decision.adverse_rate,
                    f"{prefix}.forecast_lower": decision.forecast_lower,
                    f"{prefix}.forecast_upper": decision.forecast_upper,
                    f"{prefix}.breach_probability": decision.breach_probability,
                    f"{prefix}.expected_shortfall": decision.expected_shortfall,
                    f"{prefix}.estimated_cost": decision.estimated_cost,
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
    hedge_models: tuple[HedgeModelClaim, ...] = ()


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

    expected_hedge_models = {
        item.model_id: (
            item.model_version,
            item.is_champion,
            item.status,
        )
        for item in packet.hedge_decisions
    }
    actual_hedge_models = {
        item.model_id: (
            item.model_version,
            item.is_champion,
            item.status,
        )
        for item in result.hedge_models
    }
    if len(actual_hedge_models) != len(result.hedge_models):
        errors.append("hedge_models contains duplicate model_id values")
    if actual_hedge_models != expected_hedge_models:
        errors.append(
            "hedge model identity, version, champion and status must "
            "exactly match the packet"
        )

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
        checks=tuple(
            PacketCheck(
                field=item.field,
                description=item.description,
                status=item.status,
            )
            for item in decision.checks
        ),
        source_claim_ids=decision.source_claim_ids,
        candidate_outcome=_freeze(decision.candidate_outcome),
        subject_id=decision.subject_id,
        matched=decision.matched,
        categories=decision.categories,
    )


def _freeze_action(action: RecommendedAction) -> PacketAction:
    return PacketAction(
        subject_id=action.subject_id,
        rule_ids=action.rule_ids,
        product_ids=action.product_ids,
        authority=action.authority,
        action=action.action,
        timing=action.timing,
        deadline=action.deadline,
        requirements=tuple(
            PacketRequirement(
                field=item.field,
                operator=item.operator,
                expected_value=_freeze(item.expected_value),
                description=item.description,
                current_value=_freeze(item.current_value),
            )
            for item in action.requirements
        ),
        required_documents=action.required_documents,
        document_set_ids=action.document_set_ids,
        document_requirements=tuple(
            PacketDocumentRequirement(
                requirement_id=requirement.requirement_id,
                kind=requirement.kind,
                documents=tuple(
                    PacketDocument(document.document_id, document.title)
                    for document in requirement.documents
                ),
                condition_description=requirement.condition_description,
                selector_field=requirement.selector_field,
            )
            for requirement in action.document_requirements
        ),
        steps=action.steps,
        source_ids=action.source_ids,
        source_claim_ids=action.source_claim_ids,
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


def _freeze_hedge_decision(
    decision: HedgeDecisionInput,
    *,
    is_champion: bool,
) -> PacketHedgeDecision:
    if not decision.model_id or not decision.model_version:
        raise ValueError("hedge decision model identity is required")
    if not Decimal("0") <= decision.recommended_ratio <= Decimal("1"):
        raise ValueError("hedge recommended_ratio must stay in [0, 1]")
    if decision.scenario_count < 1:
        raise ValueError("hedge decision must identify evaluated scenarios")
    return PacketHedgeDecision(
        model_id=decision.model_id,
        model_version=decision.model_version,
        objective=decision.objective,
        is_champion=is_champion,
        recommended_ratio=decision.recommended_ratio,
        sufficient=decision.sufficient,
        status=decision.status,
        adverse_rate=decision.adverse_rate,
        forecast_lower=decision.forecast_lower,
        forecast_upper=decision.forecast_upper,
        breach_probability=Decimal(repr(decision.breach_probability)),
        expected_shortfall=decision.expected_shortfall,
        estimated_cost=decision.estimated_cost,
        scenario_count=decision.scenario_count,
        parameters=_freeze(decision.parameters),
    )
