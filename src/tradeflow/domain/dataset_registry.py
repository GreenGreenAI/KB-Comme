"""Declarative registry for versioned operational datasets and parsers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from tradeflow.domain.datasets import (
    DatasetContractError,
    FxSeries,
    EligibilityEvidenceDataset,
    KsureCountryPolicyCatalog,
    SnapshotDataset,
    StaleDatasetError,
    SupportProgramCatalog,
    TradeFeedData,
    parse_ecos_usd_krw_payload,
    parse_eligibility_evidence_payload,
    parse_bizinfo_support_payload,
    parse_ksure_country_policy_payload,
    parse_trade_feed_payload,
)
from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef, require_aware
from tradeflow.domain.snapshot_file import read_snapshot, safe_segment


class DatasetKind(StrEnum):
    TRADE_FEED = "trade_feed"
    FX_SERIES = "fx_series"
    SUPPORT_PROGRAM_CATALOG = "support_program_catalog"
    COUNTRY_POLICY_CATALOG = "country_policy_catalog"
    ELIGIBILITY_EVIDENCE = "eligibility_evidence"


class StorageScope(StrEnum):
    COMMITTED_PUBLIC = "committed_public"
    RUNTIME_PRIVATE = "runtime_private"


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    source_id: str
    kind: DatasetKind
    adapter_key: str
    parser_key: str
    payload_schema_version: str
    collection_interval: timedelta
    freshness_policy: FreshnessPolicy
    storage_scope: StorageScope
    storage_root: str
    provider_key: str | None = None

    def __post_init__(self) -> None:
        safe_segment(self.dataset_id, "dataset_id")
        safe_segment(self.source_id, "source_id")
        safe_segment(self.adapter_key, "adapter_key")
        safe_segment(self.parser_key, "parser_key")
        if self.kind is DatasetKind.ELIGIBILITY_EVIDENCE:
            if self.provider_key is None:
                raise ValueError("eligibility evidence requires provider_key")
            safe_segment(self.provider_key, "provider_key")
        elif self.provider_key is not None:
            raise ValueError("provider_key is only valid for eligibility evidence")
        if not self.payload_schema_version:
            raise ValueError("payload_schema_version is required")
        if self.collection_interval <= timedelta(0):
            raise ValueError("collection_interval must be positive")
        storage_path = PurePosixPath(self.storage_root)
        if storage_path.is_absolute() or ".." in storage_path.parts:
            raise ValueError("storage_root must stay within the project")
        if not storage_path.parts:
            raise ValueError("storage_root is required")
        required_root = {
            StorageScope.COMMITTED_PUBLIC: PurePosixPath("data/snapshots"),
            StorageScope.RUNTIME_PRIVATE: PurePosixPath("data/runtime"),
        }[self.storage_scope]
        if storage_path.parts[: len(required_root.parts)] != required_root.parts:
            raise ValueError(
                f"{self.storage_scope.value} datasets must use {required_root}"
            )


class DatasetParser(Protocol):
    kind: DatasetKind
    schema_version: str

    def parse(
        self, payload: Any, ref: SnapshotRef
    ) -> (
        TradeFeedData
        | FxSeries
        | SupportProgramCatalog
        | KsureCountryPolicyCatalog
        | EligibilityEvidenceDataset
    ): ...


@dataclass(frozen=True)
class TradeFeedV1Parser:
    kind: DatasetKind = DatasetKind.TRADE_FEED
    schema_version: str = "1.0"

    def parse(self, payload: Any, ref: SnapshotRef) -> TradeFeedData:
        data = parse_trade_feed_payload(payload)
        if data.version != ref.version:
            raise DatasetContractError(
                f"feed version {data.version!r} does not match snapshot {ref.version!r}"
            )
        if data.observed_at != ref.observed_at:
            raise DatasetContractError(
                "feed observed_at does not match snapshot observed_at"
            )
        return data


@dataclass(frozen=True)
class EcosUsdKrwV1Parser:
    kind: DatasetKind = DatasetKind.FX_SERIES
    schema_version: str = "1.0"

    def parse(self, payload: Any, ref: SnapshotRef) -> FxSeries:
        series = parse_ecos_usd_krw_payload(payload)
        if series.latest.observed_on != ref.observed_at.date():
            raise DatasetContractError(
                "latest ECOS observation does not match snapshot observed_at"
            )
        return series


@dataclass(frozen=True)
class BizinfoSupportV1Parser:
    kind: DatasetKind = DatasetKind.SUPPORT_PROGRAM_CATALOG
    schema_version: str = "1.0"

    def parse(self, payload: Any, ref: SnapshotRef) -> SupportProgramCatalog:
        return parse_bizinfo_support_payload(payload)


@dataclass(frozen=True)
class KsureCountryPolicyV1Parser:
    kind: DatasetKind = DatasetKind.COUNTRY_POLICY_CATALOG
    schema_version: str = "1.0"

    def parse(
        self, payload: Any, ref: SnapshotRef
    ) -> KsureCountryPolicyCatalog:
        return parse_ksure_country_policy_payload(payload)


@dataclass(frozen=True)
class EligibilityEvidenceV1Parser:
    kind: DatasetKind = DatasetKind.ELIGIBILITY_EVIDENCE
    schema_version: str = "1.0"

    def parse(
        self, payload: Any, ref: SnapshotRef
    ) -> EligibilityEvidenceDataset:
        data = parse_eligibility_evidence_payload(payload)
        if data.version != ref.version:
            raise DatasetContractError(
                f"evidence version {data.version!r} does not match snapshot "
                f"{ref.version!r}"
            )
        if data.observed_at != ref.observed_at:
            raise DatasetContractError(
                "eligibility evidence observed_at does not match snapshot"
            )
        return data


class ParserRegistry:
    def __init__(self, parsers: Mapping[str, DatasetParser] | None = None) -> None:
        self._parsers: dict[str, DatasetParser] = {}
        for key, parser in (parsers or {}).items():
            self.register(key, parser)

    def register(self, key: str, parser: DatasetParser) -> None:
        safe_segment(key, "parser_key")
        if key in self._parsers:
            raise ValueError(f"duplicate parser_key: {key}")
        self._parsers[key] = parser

    def parse(
        self,
        definition: DatasetDefinition,
        payload: Any,
        ref: SnapshotRef,
    ) -> (
        TradeFeedData
        | FxSeries
        | SupportProgramCatalog
        | KsureCountryPolicyCatalog
        | EligibilityEvidenceDataset
    ):
        parser = self._parsers.get(definition.parser_key)
        if parser is None:
            raise DatasetContractError(
                f"unregistered parser_key: {definition.parser_key}"
            )
        if parser.kind is not definition.kind:
            raise DatasetContractError(
                f"parser {definition.parser_key} does not support {definition.kind.value}"
            )
        if parser.schema_version != definition.payload_schema_version:
            raise DatasetContractError(
                f"parser {definition.parser_key} schema {parser.schema_version} "
                f"does not match {definition.payload_schema_version}"
            )
        return parser.parse(payload, ref)

    @property
    def parsers(self) -> Mapping[str, DatasetParser]:
        return MappingProxyType(self._parsers)


class DatasetRegistry:
    def __init__(self, definitions: Iterable[DatasetDefinition]) -> None:
        items = tuple(definitions)
        definitions_by_id = {item.dataset_id: item for item in items}
        if len(definitions_by_id) != len(items):
            raise ValueError("dataset registry contains duplicate dataset_id values")
        self.definitions = MappingProxyType(definitions_by_id)

    @classmethod
    def from_json(cls, path: Path | str) -> "DatasetRegistry":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != "1.2":
            raise ValueError("unsupported dataset registry schema_version")
        return cls(_parse_definition(item) for item in document["datasets"])

    def get(self, dataset_id: str) -> DatasetDefinition:
        try:
            return self.definitions[dataset_id]
        except KeyError:
            raise KeyError(f"unknown dataset_id: {dataset_id}") from None

    def read_snapshot(
        self,
        dataset_id: str,
        path: Path | str,
        *,
        parsers: ParserRegistry,
        evaluated_at: datetime,
    ) -> SnapshotDataset:
        definition = self.get(dataset_id)
        ref, payload = read_snapshot(path)
        if ref.source_id != definition.source_id:
            raise DatasetContractError(
                f"expected {definition.source_id}, got {ref.source_id}"
            )
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        if definition.freshness_policy.evaluate(ref, evaluated_at) is Freshness.STALE:
            raise StaleDatasetError(
                f"{ref.source_id}@{ref.version} is stale at {evaluated_at.isoformat()}"
            )
        return SnapshotDataset(ref, parsers.parse(definition, payload, ref))


def default_parser_registry() -> ParserRegistry:
    return ParserRegistry(
        {
            "trade_feed_v1": TradeFeedV1Parser(),
            "ecos_usd_krw_v1": EcosUsdKrwV1Parser(),
            "bizinfo_support_v1": BizinfoSupportV1Parser(),
            "ksure_country_policy_v1": KsureCountryPolicyV1Parser(),
            "eligibility_evidence_v1": EligibilityEvidenceV1Parser(),
        }
    )


def _parse_definition(item: Mapping[str, Any]) -> DatasetDefinition:
    freshness = item.get("freshness")
    if not isinstance(freshness, Mapping):
        raise ValueError(f"{item.get('dataset_id')}: freshness must be an object")
    observation_seconds = freshness.get("max_observation_age_seconds")
    retrieval_seconds = freshness.get("max_retrieval_age_seconds")
    if isinstance(observation_seconds, bool) or not isinstance(observation_seconds, int):
        raise ValueError("max_observation_age_seconds must be an integer")
    if observation_seconds < 0:
        raise ValueError("max_observation_age_seconds must be non-negative")
    if retrieval_seconds is not None and (
        isinstance(retrieval_seconds, bool)
        or not isinstance(retrieval_seconds, int)
        or retrieval_seconds < 0
    ):
        raise ValueError("max_retrieval_age_seconds must be a non-negative integer")
    return DatasetDefinition(
        dataset_id=item["dataset_id"],
        source_id=item["source_id"],
        kind=DatasetKind(item["kind"]),
        adapter_key=item["adapter_key"],
        parser_key=item["parser_key"],
        payload_schema_version=item["payload_schema_version"],
        collection_interval=_parse_positive_seconds(
            item.get("collection_interval_seconds"),
            "collection_interval_seconds",
        ),
        freshness_policy=FreshnessPolicy(
            timedelta(seconds=observation_seconds),
            (
                timedelta(seconds=retrieval_seconds)
                if retrieval_seconds is not None
                else None
            ),
        ),
        storage_scope=StorageScope(item["storage_scope"]),
        storage_root=item["storage_root"],
        provider_key=item.get("provider_key"),
    )


def _parse_positive_seconds(value: Any, field: str) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return timedelta(seconds=value)
