"""Application boundary from verified trade snapshots to DecisionPacket."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.contracts.decision_packet import DecisionPacket
from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.dataset_registry import DatasetRegistry, ParserRegistry
from tradeflow.domain.datasets import (
    DatasetContractError,
    StaleDatasetError,
    trade_program_from_snapshot,
)
from tradeflow.domain.enums import Freshness
from tradeflow.domain.models import CompanyProfile
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import (
    SnapshotIntegrityError,
    safe_segment,
    snapshot_path,
)
from tradeflow.knowledge.facts import FactAssertion
from tradeflow.knowledge.mutual_account import MutualAccountTimeline
from tradeflow.runtime.pipeline import TradeFlowPipeline

BUSINESS_TIMEZONE = timezone(timedelta(hours=9), name="Asia/Seoul")


class AnalysisErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNKNOWN_DATASET = "unknown_dataset"
    SNAPSHOT_NOT_FOUND = "snapshot_not_found"
    SNAPSHOT_INVALID = "snapshot_invalid"
    SNAPSHOT_STALE = "snapshot_stale"
    WRONG_DATASET_KIND = "wrong_dataset_kind"
    INVALID_CASE_INPUT = "invalid_case_input"


class AnalysisServiceError(RuntimeError):
    def __init__(self, code: AnalysisErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SnapshotAnalysisRequest:
    dataset_id: str
    snapshot_version: str
    program_id: str
    company: CompanyProfile
    as_of: date

    def __post_init__(self) -> None:
        safe_segment(self.dataset_id, "dataset_id")
        safe_segment(self.snapshot_version, "snapshot_version")
        safe_segment(self.program_id, "program_id")
        if not isinstance(self.company, CompanyProfile):
            raise TypeError("company must be a CompanyProfile")
        if not isinstance(self.as_of, date) or isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a date")


@dataclass(frozen=True)
class CaseAnalysisInputs:
    assertions_by_case: Mapping[str, tuple[FactAssertion, ...]]
    evidence: tuple[EvidenceDescriptor, ...] = ()
    source_freshness: Mapping[str, Freshness] = field(default_factory=dict)
    mutual_account_timelines: Mapping[str, MutualAccountTimeline] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        assertions = {
            case_id: tuple(items)
            for case_id, items in self.assertions_by_case.items()
        }
        freshness = dict(self.source_freshness or {})
        timelines = dict(self.mutual_account_timelines or {})
        object.__setattr__(
            self, "assertions_by_case", MappingProxyType(assertions)
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(
            self, "source_freshness", MappingProxyType(freshness)
        )
        object.__setattr__(
            self, "mutual_account_timelines", MappingProxyType(timelines)
        )


class AnalysisService:
    def __init__(
        self,
        *,
        project_root: Path | str,
        datasets: DatasetRegistry,
        parsers: ParserRegistry,
        pipeline: TradeFlowPipeline,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.datasets = datasets
        self.parsers = parsers
        self.pipeline = pipeline

    def analyze(
        self,
        request: SnapshotAnalysisRequest,
        *,
        evaluated_at: datetime,
        case_inputs: CaseAnalysisInputs | None = None,
    ) -> DecisionPacket:
        if not isinstance(request, SnapshotAnalysisRequest):
            raise TypeError("request must be a SnapshotAnalysisRequest")
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        if request.as_of > evaluated_at.astimezone(BUSINESS_TIMEZONE).date():
            raise AnalysisServiceError(
                AnalysisErrorCode.INVALID_REQUEST,
                "as_of cannot be later than evaluated_at",
            )
        try:
            definition = self.datasets.get(request.dataset_id)
        except KeyError:
            raise AnalysisServiceError(
                AnalysisErrorCode.UNKNOWN_DATASET,
                f"unknown dataset_id: {request.dataset_id}",
            ) from None

        root = (self.project_root / definition.storage_root).resolve()
        try:
            root.relative_to(self.project_root)
        except ValueError:
            raise AnalysisServiceError(
                AnalysisErrorCode.SNAPSHOT_INVALID,
                "dataset storage root leaves the project",
            ) from None
        path = snapshot_path(
            root, definition.source_id, request.snapshot_version
        )
        try:
            dataset = self.datasets.read_snapshot(
                request.dataset_id,
                path,
                parsers=self.parsers,
                evaluated_at=evaluated_at,
            )
        except FileNotFoundError:
            raise AnalysisServiceError(
                AnalysisErrorCode.SNAPSHOT_NOT_FOUND,
                f"snapshot not found: {request.dataset_id}@{request.snapshot_version}",
            ) from None
        except StaleDatasetError:
            raise AnalysisServiceError(
                AnalysisErrorCode.SNAPSHOT_STALE,
                f"snapshot is stale: {request.dataset_id}@{request.snapshot_version}",
            ) from None
        except (DatasetContractError, SnapshotIntegrityError, KeyError, ValueError):
            raise AnalysisServiceError(
                AnalysisErrorCode.SNAPSHOT_INVALID,
                f"snapshot is invalid: {request.dataset_id}@{request.snapshot_version}",
            ) from None

        if (
            dataset.ref.observed_at.astimezone(BUSINESS_TIMEZONE).date()
            > request.as_of
            or dataset.ref.retrieved_at.astimezone(BUSINESS_TIMEZONE).date()
            > request.as_of
        ):
            raise AnalysisServiceError(
                AnalysisErrorCode.SNAPSHOT_INVALID,
                "snapshot cannot postdate the analysis as_of date",
            )

        try:
            program = trade_program_from_snapshot(
                dataset,
                program_id=request.program_id,
                company=request.company,
                as_of=request.as_of,
            )
        except TypeError:
            raise AnalysisServiceError(
                AnalysisErrorCode.WRONG_DATASET_KIND,
                f"dataset is not a trade feed: {request.dataset_id}",
            ) from None

        if case_inputs is None:
            return self.pipeline.analyze_packet(program)
        try:
            return self.pipeline.analyze_case_packet(
                program,
                assertions_by_case=case_inputs.assertions_by_case,
                evidence=case_inputs.evidence,
                source_freshness=case_inputs.source_freshness,
                mutual_account_timelines=case_inputs.mutual_account_timelines,
            )
        except ValueError as exc:
            raise AnalysisServiceError(
                AnalysisErrorCode.INVALID_CASE_INPUT,
                str(exc),
            ) from None


def snapshot_analysis_request_from_document(
    document: Mapping[str, Any],
) -> SnapshotAnalysisRequest:
    """Parse the versioned JSON request body without lossy numeric coercion."""
    try:
        if not isinstance(document, Mapping):
            raise ValueError("request body must be an object")
        allowed = {
            "schema_version",
            "dataset_id",
            "snapshot_version",
            "program_id",
            "company",
            "as_of",
        }
        unknown = set(document) - allowed
        if unknown:
            raise ValueError("unknown request fields: " + ", ".join(sorted(unknown)))
        if document.get("schema_version") != "1.0":
            raise ValueError("unsupported request schema_version")
        company_document = document.get("company")
        if not isinstance(company_document, Mapping):
            raise ValueError("company must be an object")
        company_allowed = {
            "company_id",
            "name",
            "country_code",
            "is_sme",
            "annual_export_usd",
            "industry_code",
            "attributes",
        }
        unknown_company = set(company_document) - company_allowed
        if unknown_company:
            raise ValueError(
                "unknown company fields: " + ", ".join(sorted(unknown_company))
            )
        is_sme = company_document.get("is_sme")
        if is_sme is not None and not isinstance(is_sme, bool):
            raise ValueError("company.is_sme must be boolean or null")
        attributes = company_document.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise ValueError("company.attributes must be an object")
        annual_export = _optional_decimal_string(
            company_document.get("annual_export_usd"),
            "company.annual_export_usd",
        )
        if annual_export is not None and annual_export < 0:
            raise ValueError("company.annual_export_usd must be non-negative")
        as_of_value = _required_string(document, "as_of")
        try:
            as_of = date.fromisoformat(as_of_value)
        except ValueError:
            raise ValueError("as_of must be an ISO date") from None
        company = CompanyProfile(
            company_id=_required_string(company_document, "company_id"),
            name=_required_string(company_document, "name"),
            country_code=_optional_string(company_document, "country_code") or "KR",
            is_sme=is_sme,
            annual_export_usd=annual_export,
            industry_code=_optional_string(company_document, "industry_code"),
            attributes=dict(attributes),
        )
        return SnapshotAnalysisRequest(
            dataset_id=_required_string(document, "dataset_id"),
            snapshot_version=_required_string(document, "snapshot_version"),
            program_id=_required_string(document, "program_id"),
            company=company,
            as_of=as_of,
        )
    except (TypeError, ValueError) as exc:
        raise AnalysisServiceError(
            AnalysisErrorCode.INVALID_REQUEST,
            str(exc),
        ) from None


def decision_packet_document(packet: DecisionPacket) -> dict[str, Any]:
    """Build a JSON-compatible response without converting Decimal to float."""
    if not isinstance(packet, DecisionPacket):
        raise TypeError("packet must be a DecisionPacket")
    document = _json_value(packet)
    assert isinstance(document, dict)
    return document


_FROZEN_MAPPING_FIELDS = {
    "candidate_outcome",
    "current_value",
    "expected_value",
    "payload",
    "value",
}


def _json_value(value: Any, *, mapping_hint: bool = False) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _json_value(
                getattr(value, item.name),
                mapping_hint=item.name in _FROZEN_MAPPING_FIELDS,
            )
            for item in fields(value)
        }
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        is_frozen_mapping = all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        )
        if mapping_hint and is_frozen_mapping:
            return {item[0]: _json_value(item[1]) for item in value}
        if value and is_frozen_mapping:
            return {item[0]: _json_value(item[1]) for item in value}
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _required_string(document: Mapping[str, Any], field_name: str) -> str:
    value = document.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(document: Mapping[str, Any], field_name: str) -> str | None:
    value = document.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    return value.strip() or None


def _optional_decimal_string(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a decimal string or null")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{field_name} is not a valid decimal") from None
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result
