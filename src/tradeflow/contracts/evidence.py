from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from tradeflow.domain.enums import EvidenceRole


@dataclass(frozen=True)
class EvidenceRequirement:
    role: EvidenceRole
    identifiers: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True)
class EvidenceDescriptor:
    evidence_id: str
    role: EvidenceRole
    identifiers: tuple[str, ...]
    source_ids: tuple[str, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = field(default_factory=dict)

