"""Stable interfaces shared by independently owned TradeFlow modules."""

from tradeflow.contracts.decision_packet import (
    DecisionPacket,
    DecisionStatusClaim,
    NumericClaim,
    PacketAction,
    PacketDecision,
    PacketEvidence,
    PacketRequirement,
    SynthesisResult,
    validate_synthesis,
)
from tradeflow.contracts.evidence import EvidenceDescriptor, EvidenceRequirement
from tradeflow.contracts.interfaces import ExposureService, KnowledgeService
from tradeflow.contracts.profile_policy import (
    CapabilityRequest,
    FactProvenance,
    PolicyRoute,
    ProfileFact,
    ProfilePolicyResult,
    SegmentClassification,
    SegmentMatch,
    UserProfileFacts,
)

__all__ = [
    "DecisionPacket",
    "DecisionStatusClaim",
    "EvidenceDescriptor",
    "EvidenceRequirement",
    "ExposureService",
    "KnowledgeService",
    "CapabilityRequest",
    "FactProvenance",
    "NumericClaim",
    "PacketAction",
    "PacketDecision",
    "PacketEvidence",
    "PacketRequirement",
    "PolicyRoute",
    "ProfileFact",
    "ProfilePolicyResult",
    "SegmentClassification",
    "SegmentMatch",
    "SynthesisResult",
    "UserProfileFacts",
    "validate_synthesis",
]
