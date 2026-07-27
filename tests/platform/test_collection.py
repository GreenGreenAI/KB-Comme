import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradeflow.domain.dataset_registry import (
    DatasetRegistry,
    default_parser_registry,
)
from tradeflow.integration.collection import (
    CollectionOrchestrator,
    CollectionRequest,
    CollectionStatus,
)
from tradeflow.integration.registry import AdapterRegistry
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))
DATASET_ID = "BIZINFO_SUPPORT_PROGRAMS_DAILY"


def _payload(program_id: str = "P-1") -> dict:
    return {
        "jsonArray": {
            "item": [
                {
                    "pblancId": program_id,
                    "pblancNm": "수출 지원",
                    "jrsdInsttNm": "중소벤처기업부",
                    "pldirSportRealmLclasCodeNm": "수출",
                    "trgetNm": "중소기업",
                    "pblancUrl": "https://www.bizinfo.go.kr/example",
                    "totCnt": "1",
                }
            ]
        }
    }


class _Adapter:
    source_id = "BIZINFO_SUPPORT_API"
    adapter_key = "bizinfo_support"

    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def collect(self, root, *, retrieved_at, **parameters):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary outage")
        version = retrieved_at.astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        return write_snapshot(
            root,
            build_envelope(
                source_id=self.source_id,
                version=version,
                observed_at=retrieved_at,
                retrieved_at=retrieved_at,
                payload=_payload(parameters.get("program_id", "P-1")),
            ),
        )


class CollectionRequestTests(unittest.TestCase):
    def test_request_is_immutable_and_reserves_collection_time(self) -> None:
        source = {"program_id": "P-2"}
        request = CollectionRequest(DATASET_ID, source, max_attempts=2)
        source["program_id"] = "changed"

        self.assertEqual("P-2", request.parameters["program_id"])
        with self.assertRaises(TypeError):
            request.parameters["new"] = "value"
        with self.assertRaisesRegex(ValueError, "retrieved_at"):
            CollectionRequest(DATASET_ID, {"retrieved_at": "caller-owned"})
        with self.assertRaisesRegex(ValueError, "between 1 and 5"):
            CollectionRequest(DATASET_ID, max_attempts=6)


class CollectionOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project_root = Path(self.tmp.name)
        self.datasets = DatasetRegistry.from_json(
            ROOT / "data" / "dataset_registry.json"
        )
        self.adapters = AdapterRegistry(self.datasets)
        self.at = datetime(2026, 7, 27, 9, tzinfo=KST)

    def orchestrator(self) -> CollectionOrchestrator:
        return CollectionOrchestrator(
            project_root=self.project_root,
            datasets=self.datasets,
            parsers=default_parser_registry(),
            adapters=self.adapters,
        )

    def test_due_collection_is_verified_then_skipped_until_interval(self) -> None:
        adapter = _Adapter()
        self.adapters.register(DATASET_ID, adapter)
        orchestrator = self.orchestrator()

        self.assertTrue(orchestrator.is_due(DATASET_ID, evaluated_at=self.at))
        first = orchestrator.collect(
            CollectionRequest(DATASET_ID), attempted_at=self.at
        )
        second = orchestrator.collect(
            CollectionRequest(DATASET_ID),
            attempted_at=self.at + timedelta(hours=12),
        )

        self.assertEqual(CollectionStatus.COLLECTED, first.status)
        self.assertTrue(first.usable)
        self.assertEqual("P-1", first.dataset.value.programs[0].program_id)
        self.assertEqual(CollectionStatus.SKIPPED, second.status)
        self.assertEqual(0, second.attempts)
        self.assertEqual(1, adapter.calls)

    def test_retry_succeeds_within_bounded_attempt_count(self) -> None:
        adapter = _Adapter(failures=2)
        self.adapters.register(DATASET_ID, adapter)

        result = self.orchestrator().collect(
            CollectionRequest(DATASET_ID, max_attempts=3),
            attempted_at=self.at,
        )

        self.assertEqual(CollectionStatus.COLLECTED, result.status)
        self.assertEqual(3, result.attempts)
        self.assertEqual(3, adapter.calls)

    def test_failed_refresh_uses_only_a_fresh_verified_fallback(self) -> None:
        good = _Adapter()
        self.adapters.register(DATASET_ID, good)
        orchestrator = self.orchestrator()
        collected = orchestrator.collect(
            CollectionRequest(DATASET_ID), attempted_at=self.at
        )
        self.assertEqual(CollectionStatus.COLLECTED, collected.status)

        failing_registry = AdapterRegistry(self.datasets)
        failing = _Adapter(failures=5)
        failing_registry.register(DATASET_ID, failing)
        orchestrator = CollectionOrchestrator(
            project_root=self.project_root,
            datasets=self.datasets,
            parsers=default_parser_registry(),
            adapters=failing_registry,
        )
        result = orchestrator.collect(
            CollectionRequest(DATASET_ID, max_attempts=2, force=True),
            attempted_at=self.at + timedelta(hours=12),
        )

        self.assertEqual(CollectionStatus.FALLBACK, result.status)
        self.assertEqual(2, result.attempts)
        self.assertTrue(result.usable)
        self.assertIn("temporary outage", result.error)
        self.assertEqual(collected.snapshot_path, result.snapshot_path)

    def test_stale_or_missing_fallback_returns_structured_failure(self) -> None:
        definition = self.datasets.get(DATASET_ID)
        stale_at = self.at - timedelta(days=3)
        write_snapshot(
            self.project_root / definition.storage_root,
            build_envelope(
                source_id=definition.source_id,
                version="stale-v1",
                observed_at=stale_at,
                retrieved_at=stale_at,
                payload=_payload(),
            ),
        )
        failing = _Adapter(failures=5)
        self.adapters.register(DATASET_ID, failing)

        stale = self.orchestrator().collect(
            CollectionRequest(DATASET_ID, max_attempts=2), attempted_at=self.at
        )

        self.assertEqual(CollectionStatus.FAILED, stale.status)
        self.assertFalse(stale.usable)
        self.assertIsNone(stale.dataset)
        self.assertNotIn(str(self.project_root), stale.error)

        empty_root = Path(self.tmp.name) / "empty-project"
        missing = CollectionOrchestrator(
            project_root=empty_root,
            datasets=self.datasets,
            parsers=default_parser_registry(),
            adapters=AdapterRegistry(self.datasets),
        ).collect(
            CollectionRequest(DATASET_ID, force=True), attempted_at=self.at
        )
        self.assertEqual(CollectionStatus.FAILED, missing.status)
        self.assertIn("no adapter", missing.error)

    def test_batch_keeps_individual_results_and_rejects_duplicates(self) -> None:
        adapter = _Adapter()
        self.adapters.register(DATASET_ID, adapter)
        orchestrator = self.orchestrator()

        results = orchestrator.collect_many(
            (
                CollectionRequest(DATASET_ID),
                CollectionRequest("ERP_TRADE_FEED_V1", force=True),
            ),
            attempted_at=self.at,
        )
        self.assertEqual(
            (CollectionStatus.COLLECTED, CollectionStatus.FAILED),
            tuple(result.status for result in results),
        )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            orchestrator.collect_many(
                (CollectionRequest(DATASET_ID), CollectionRequest(DATASET_ID)),
                attempted_at=self.at,
            )


if __name__ == "__main__":
    unittest.main()
