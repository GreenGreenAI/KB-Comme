"""Deterministic orchestration for registered snapshot collectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from tradeflow.domain.dataset_registry import (
    DatasetDefinition,
    DatasetRegistry,
    ParserRegistry,
)
from tradeflow.domain.datasets import DatasetContractError, SnapshotDataset
from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import (
    SnapshotNotFoundError,
    latest_snapshot_path,
    read_snapshot,
)
from tradeflow.integration.registry import AdapterRegistry


class CollectionStatus(StrEnum):
    COLLECTED = "collected"
    SKIPPED = "skipped"
    FALLBACK = "fallback"
    FAILED = "failed"


@dataclass(frozen=True)
class CollectionRequest:
    dataset_id: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    max_attempts: int = 1
    force: bool = False

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("dataset_id is required")
        if isinstance(self.max_attempts, bool) or not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        parameters = dict(self.parameters)
        if "retrieved_at" in parameters:
            raise ValueError("retrieved_at is controlled by the orchestrator")
        object.__setattr__(self, "parameters", MappingProxyType(parameters))


@dataclass(frozen=True)
class CollectionResult:
    dataset_id: str
    status: CollectionStatus
    attempted_at: datetime
    attempts: int
    snapshot_path: Path | None
    dataset: SnapshotDataset | None
    error: str | None = None

    @property
    def usable(self) -> bool:
        return self.dataset is not None and self.status is not CollectionStatus.FAILED


class CollectionOrchestrator:
    """Collect due datasets and return verified, freshness-gated results.

    A process scheduler may invoke this class periodically. This class owns the
    repeatable decision about whether a dataset is due, how often an adapter is
    retried, and whether an existing snapshot is still safe after an outage.
    """

    def __init__(
        self,
        *,
        project_root: Path | str,
        datasets: DatasetRegistry,
        parsers: ParserRegistry,
        adapters: AdapterRegistry,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.datasets = datasets
        self.parsers = parsers
        self.adapters = adapters

    def storage_root(self, definition: DatasetDefinition) -> Path:
        root = (self.project_root / definition.storage_root).resolve()
        try:
            root.relative_to(self.project_root)
        except ValueError:
            raise ValueError(
                f"{definition.dataset_id}: storage root leaves project"
            ) from None
        return root

    def is_due(self, dataset_id: str, *, evaluated_at: datetime) -> bool:
        definition = self.datasets.get(dataset_id)
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        root = self.storage_root(definition)
        try:
            path = latest_snapshot_path(root, definition.source_id)
        except SnapshotNotFoundError:
            return True
        ref, _ = read_snapshot(path)
        if ref.retrieved_at > evaluated_at:
            return True
        if definition.freshness_policy.evaluate(ref, evaluated_at) is Freshness.STALE:
            return True
        return evaluated_at - ref.retrieved_at >= definition.collection_interval

    def collect(
        self,
        request: CollectionRequest,
        *,
        attempted_at: datetime,
    ) -> CollectionResult:
        attempted_at = require_aware(attempted_at, "attempted_at")
        definition = self.datasets.get(request.dataset_id)
        root = self.storage_root(definition)

        try:
            due = request.force or self.is_due(
                request.dataset_id, evaluated_at=attempted_at
            )
        except (RuntimeError, OSError, ValueError) as exc:
            return CollectionResult(
                request.dataset_id,
                CollectionStatus.FAILED,
                attempted_at,
                0,
                None,
                None,
                f"collection schedule state is invalid: {type(exc).__name__}",
            )

        if not due:
            path = latest_snapshot_path(root, definition.source_id)
            dataset = self.datasets.read_snapshot(
                request.dataset_id,
                path,
                parsers=self.parsers,
                evaluated_at=attempted_at,
            )
            return CollectionResult(
                request.dataset_id,
                CollectionStatus.SKIPPED,
                attempted_at,
                0,
                path,
                dataset,
            )

        attempts = 0
        last_error: Exception | None = None
        try:
            adapter = self.adapters.get(request.dataset_id)
        except KeyError as exc:
            return self._fallback_or_failure(
                request.dataset_id,
                definition,
                root,
                attempted_at,
                attempts=0,
                error=exc,
            )

        for attempts in range(1, request.max_attempts + 1):
            try:
                path = adapter.collect(
                    root,
                    retrieved_at=attempted_at,
                    **request.parameters,
                )
                dataset = self.datasets.read_snapshot(
                    request.dataset_id,
                    path,
                    parsers=self.parsers,
                    evaluated_at=attempted_at,
                )
                return CollectionResult(
                    request.dataset_id,
                    CollectionStatus.COLLECTED,
                    attempted_at,
                    attempts,
                    path,
                    dataset,
                )
            except (
                RuntimeError,
                OSError,
                DatasetContractError,
                KeyError,
                ValueError,
            ) as exc:
                last_error = exc

        assert last_error is not None
        return self._fallback_or_failure(
            request.dataset_id,
            definition,
            root,
            attempted_at,
            attempts=attempts,
            error=last_error,
        )

    def collect_many(
        self,
        requests: Iterable[CollectionRequest],
        *,
        attempted_at: datetime,
    ) -> tuple[CollectionResult, ...]:
        requests = tuple(requests)
        ids = [request.dataset_id for request in requests]
        if len(ids) != len(set(ids)):
            raise ValueError("collection batch contains duplicate dataset_id values")
        return tuple(
            self.collect(request, attempted_at=attempted_at)
            for request in requests
        )

    def _fallback_or_failure(
        self,
        dataset_id: str,
        definition: DatasetDefinition,
        root: Path,
        attempted_at: datetime,
        *,
        attempts: int,
        error: Exception,
    ) -> CollectionResult:
        safe_error = f"{type(error).__name__}: {error}"
        try:
            path = latest_snapshot_path(root, definition.source_id)
            dataset = self.datasets.read_snapshot(
                dataset_id,
                path,
                parsers=self.parsers,
                evaluated_at=attempted_at,
            )
        except (RuntimeError, OSError, ValueError, KeyError) as fallback_error:
            return CollectionResult(
                dataset_id,
                CollectionStatus.FAILED,
                attempted_at,
                attempts,
                None,
                None,
                f"{safe_error}; fallback unavailable: "
                f"{type(fallback_error).__name__}",
            )
        return CollectionResult(
            dataset_id,
            CollectionStatus.FALLBACK,
            attempted_at,
            attempts,
            path,
            dataset,
            safe_error,
        )
