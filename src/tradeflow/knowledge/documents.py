from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from tradeflow.domain.enums import DocumentRequirementKind
from tradeflow.domain.models import DocumentOption, DocumentRequirementGroup


@dataclass(frozen=True)
class ApplicationDocumentSet:
    """A versioned official document checklist for one product and stage."""

    document_set_id: str
    product_id: str
    stage: str
    version: str
    source_ids: tuple[str, ...]
    source_claim_ids: tuple[str, ...]
    requirements: tuple[DocumentRequirementGroup, ...]
    effective_from: date | None = None
    effective_to: date | None = None
    status: str = "draft"

    def __post_init__(self) -> None:
        for label, value in (
            ("document_set_id", self.document_set_id),
            ("product_id", self.product_id),
            ("stage", self.stage),
            ("version", self.version),
        ):
            if not value:
                raise ValueError(f"application document set {label} must not be empty")
        if not self.source_ids or not self.source_claim_ids:
            raise ValueError(
                f"{self.document_set_id}: source_ids and source_claim_ids are required"
            )
        if not self.requirements:
            raise ValueError(f"{self.document_set_id}: requirements must not be empty")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError(f"{self.document_set_id}: duplicate source_id")
        if len(set(self.source_claim_ids)) != len(self.source_claim_ids):
            raise ValueError(f"{self.document_set_id}: duplicate source_claim_id")
        requirement_ids = [item.requirement_id for item in self.requirements]
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError(f"{self.document_set_id}: duplicate requirement_id")
        document_ids = [
            document.document_id
            for requirement in self.requirements
            for document in requirement.documents
        ]
        if len(set(document_ids)) != len(document_ids):
            raise ValueError(f"{self.document_set_id}: duplicate document_id")
        if self.status not in {"draft", "active", "retired"}:
            raise ValueError(f"{self.document_set_id}: unsupported status")
        if self.effective_from and self.effective_to:
            if self.effective_from > self.effective_to:
                raise ValueError(f"{self.document_set_id}: invalid effective period")

    def effective_on(self, target_date: date) -> bool:
        return not (
            (self.effective_from and target_date < self.effective_from)
            or (self.effective_to and target_date > self.effective_to)
        )

    @property
    def universally_required_titles(self) -> tuple[str, ...]:
        return tuple(
            document.title
            for requirement in self.requirements
            if requirement.kind is DocumentRequirementKind.REQUIRED
            for document in requirement.documents
        )


class DocumentCatalog:
    def __init__(self, document_sets: Iterable[ApplicationDocumentSet] = ()) -> None:
        values = tuple(document_sets)
        self.document_sets = {item.document_set_id: item for item in values}
        if len(self.document_sets) != len(values):
            raise ValueError("document catalog contains duplicate document_set_id values")

    @classmethod
    def from_json(cls, path: Path) -> "DocumentCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            raise ValueError(f"{path}: unsupported document catalog schema_version")
        return cls(_parse_document_set(item) for item in payload.get("document_sets", []))


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_document_set(item: dict) -> ApplicationDocumentSet:
    return ApplicationDocumentSet(
        document_set_id=item["document_set_id"],
        product_id=item["product_id"],
        stage=item["stage"],
        version=item["version"],
        source_ids=tuple(item.get("source_ids", [])),
        source_claim_ids=tuple(item.get("source_claim_ids", [])),
        requirements=tuple(
            DocumentRequirementGroup(
                requirement_id=requirement["requirement_id"],
                kind=DocumentRequirementKind(requirement["kind"]),
                documents=tuple(
                    DocumentOption(
                        document_id=document["document_id"],
                        title=document["title"],
                    )
                    for document in requirement.get("documents", [])
                ),
                condition_description=requirement.get("condition_description"),
                selector_field=requirement.get("selector_field"),
            )
            for requirement in item.get("requirements", [])
        ),
        effective_from=_parse_date(item.get("effective_from")),
        effective_to=_parse_date(item.get("effective_to")),
        status=item.get("status", "draft"),
    )
