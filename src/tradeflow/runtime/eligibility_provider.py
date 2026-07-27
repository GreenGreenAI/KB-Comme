"""Convert verified private snapshots into eligibility provider records."""

from __future__ import annotations

from datetime import datetime

from tradeflow.domain.dataset_registry import DatasetDefinition, DatasetKind
from tradeflow.domain.datasets import (
    EligibilityEvidenceDataset,
    SnapshotDataset,
    StaleDatasetError,
)
from tradeflow.domain.enums import EvidenceSubjectKind, Freshness
from tradeflow.domain.models import TradeProgram
from tradeflow.domain.snapshot import require_aware
from tradeflow.knowledge.eligibility_evidence import (
    EligibilityEvidenceRecord,
    EvidenceMetadata,
)


class SnapshotEligibilityEvidenceProvider:
    """Eligibility provider backed by one hash-verified snapshot dataset."""

    def __init__(
        self,
        dataset: SnapshotDataset,
        *,
        definition: DatasetDefinition,
    ) -> None:
        if not isinstance(dataset.value, EligibilityEvidenceDataset):
            raise TypeError("dataset is not eligibility evidence")
        if definition.kind is not DatasetKind.ELIGIBILITY_EVIDENCE:
            raise TypeError("definition is not eligibility evidence")
        if dataset.ref.source_id != definition.source_id:
            raise ValueError("dataset source_id does not match definition")
        if dataset.value.provider_key != definition.provider_key:
            raise ValueError("dataset provider_key does not match definition")
        self.dataset = dataset
        self.definition = definition
        self.provider_key = dataset.value.provider_key

    def collect(
        self,
        *,
        program: TradeProgram,
        evaluated_at: datetime,
    ) -> tuple[EligibilityEvidenceRecord, ...]:
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        ref = self.dataset.ref
        if (
            self.definition.freshness_policy.evaluate(ref, evaluated_at)
            is Freshness.STALE
        ):
            raise StaleDatasetError(
                f"{ref.source_id}@{ref.version} is stale at "
                f"{evaluated_at.isoformat()}"
            )
        case_ids = {case.case_id for case in program.cases}
        records: list[EligibilityEvidenceRecord] = []
        for item in self.dataset.value.records:
            if item.company_id != program.company.company_id:
                continue
            if (
                item.subject_kind is EvidenceSubjectKind.CASE
                and item.subject_id not in case_ids
            ):
                continue
            records.append(
                EligibilityEvidenceRecord(
                    metadata=EvidenceMetadata(
                        evidence_id=item.evidence_id,
                        source_id=ref.source_id,
                        observed_at=ref.observed_at,
                        retrieved_at=ref.retrieved_at,
                        valid_until=item.valid_until,
                        content_hash=ref.content_hash,
                    ),
                    subject_kind=item.subject_kind,
                    subject_id=item.subject_id,
                    company_id=item.company_id,
                    facts=item.facts,
                    provider_key=self.provider_key,
                )
            )
        return tuple(records)
