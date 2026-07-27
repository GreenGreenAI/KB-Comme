"""Runtime adapter bindings for declaratively registered datasets."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.domain.dataset_registry import DatasetRegistry


class AdapterRegistry:
    def __init__(self, datasets: DatasetRegistry) -> None:
        self.datasets = datasets
        self._adapters: dict[str, Any] = {}

    def register(self, dataset_id: str, adapter: Any) -> None:
        definition = self.datasets.get(dataset_id)
        if dataset_id in self._adapters:
            raise ValueError(f"adapter already registered for {dataset_id}")
        source_id = getattr(adapter, "source_id", None)
        if source_id != definition.source_id:
            raise ValueError(
                f"{dataset_id}: adapter source_id {source_id!r} does not match "
                f"{definition.source_id!r}"
            )
        adapter_key = getattr(adapter, "adapter_key", None)
        if adapter_key != definition.adapter_key:
            raise ValueError(
                f"{dataset_id}: adapter_key {adapter_key!r} does not match "
                f"{definition.adapter_key!r}"
            )
        self._adapters[dataset_id] = adapter

    def get(self, dataset_id: str) -> Any:
        self.datasets.get(dataset_id)
        try:
            return self._adapters[dataset_id]
        except KeyError:
            raise KeyError(f"no adapter registered for {dataset_id}") from None

    @property
    def adapters(self) -> Mapping[str, Any]:
        return MappingProxyType(self._adapters)
