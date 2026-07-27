import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradeflow.domain.dataset_registry import (
    DatasetKind,
    DatasetRegistry,
    ParserRegistry,
    StorageScope,
    default_parser_registry,
)
from tradeflow.domain.datasets import (
    DatasetContractError,
    FxSeries,
    StaleDatasetError,
    TradeFeedData,
)
from tradeflow.integration.ecos import EcosFxAdapter
from tradeflow.integration.registry import AdapterRegistry
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot
from tradeflow.integration.trade_feed import JsonTradeFeedAdapter

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))


def _trade_payload(*, observed_at: str = "2026-07-27T09:00:00+09:00") -> dict:
    return {
        "schema_version": "1.0",
        "version": "erp-v1",
        "observed_at": observed_at,
        "opening_balances": {"USD": "100"},
        "trades": [
            {
                "case_id": "T1",
                "direction": "export",
                "currency": "USD",
                "amount": "1000",
                "expected_payment_date": "2026-08-01",
                "payment_method": "tt",
            }
        ],
    }


class DatasetRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DatasetRegistry.from_json(
            ROOT / "data" / "dataset_registry.json"
        )

    def test_committed_registry_declares_public_and_private_datasets(self) -> None:
        self.assertEqual(
            {"ECOS_USD_KRW_DAILY", "ERP_TRADE_FEED_V1"},
            set(self.registry.definitions),
        )
        ecos = self.registry.get("ECOS_USD_KRW_DAILY")
        erp = self.registry.get("ERP_TRADE_FEED_V1")
        self.assertEqual(DatasetKind.FX_SERIES, ecos.kind)
        self.assertEqual(StorageScope.COMMITTED_PUBLIC, ecos.storage_scope)
        self.assertEqual(StorageScope.RUNTIME_PRIVATE, erp.storage_scope)
        self.assertEqual("data/snapshots", ecos.storage_root)
        self.assertEqual("data/runtime", erp.storage_root)
        with self.assertRaises(TypeError):
            self.registry.definitions["NEW"] = erp
        with self.assertRaisesRegex(ValueError, "within the project"):
            replace(erp, storage_root="../outside")
        with self.assertRaisesRegex(ValueError, "must use data/runtime"):
            replace(erp, storage_root="data/snapshots")

    def test_registry_reads_committed_ecos_through_registered_parser(self) -> None:
        dataset = self.registry.read_snapshot(
            "ECOS_USD_KRW_DAILY",
            ROOT / "data" / "snapshots" / "ECOS_USD_KRW" / "2026-07-24.json",
            parsers=default_parser_registry(),
            evaluated_at=datetime(2026, 7, 27, tzinfo=KST),
        )

        self.assertIsInstance(dataset.value, FxSeries)
        self.assertEqual("ECOS_USD_KRW", dataset.ref.source_id)

    def test_private_trade_snapshot_uses_registry_freshness_and_parser(self) -> None:
        payload = _trade_payload()
        observed = datetime.fromisoformat(payload["observed_at"])
        with tempfile.TemporaryDirectory() as tmp:
            envelope = build_envelope(
                source_id="ERP_TRADE_FEED",
                version=payload["version"],
                observed_at=observed,
                retrieved_at=observed,
                payload=payload,
            )
            path = write_snapshot(tmp, envelope)
            dataset = self.registry.read_snapshot(
                "ERP_TRADE_FEED_V1",
                path,
                parsers=default_parser_registry(),
                evaluated_at=observed + timedelta(hours=1),
            )
            self.assertIsInstance(dataset.value, TradeFeedData)

            with self.assertRaisesRegex(StaleDatasetError, "stale"):
                self.registry.read_snapshot(
                    "ERP_TRADE_FEED_V1",
                    path,
                    parsers=default_parser_registry(),
                    evaluated_at=observed + timedelta(days=2),
                )

    def test_unregistered_or_contract_mismatched_parser_is_rejected(self) -> None:
        definition = self.registry.get("ERP_TRADE_FEED_V1")
        ref_time = datetime(2026, 7, 27, 9, tzinfo=KST)
        with tempfile.TemporaryDirectory() as tmp:
            payload = _trade_payload()
            path = write_snapshot(
                tmp,
                build_envelope(
                    source_id=definition.source_id,
                    version="erp-v1",
                    observed_at=ref_time,
                    retrieved_at=ref_time,
                    payload=payload,
                ),
            )
            with self.assertRaisesRegex(DatasetContractError, "unregistered"):
                self.registry.read_snapshot(
                    definition.dataset_id,
                    path,
                    parsers=ParserRegistry(),
                    evaluated_at=ref_time,
                )

            mismatched = DatasetRegistry(
                (replace(definition, payload_schema_version="2.0"),)
            )
            with self.assertRaisesRegex(DatasetContractError, "does not match"):
                mismatched.read_snapshot(
                    definition.dataset_id,
                    path,
                    parsers=default_parser_registry(),
                    evaluated_at=ref_time,
                )


class AdapterRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.datasets = DatasetRegistry.from_json(
            ROOT / "data" / "dataset_registry.json"
        )
        self.adapters = AdapterRegistry(self.datasets)

    def test_existing_adapters_bind_to_declarative_definitions(self) -> None:
        ecos = EcosFxAdapter()
        erp = JsonTradeFeedAdapter(
            endpoint="https://erp.example/trades",
            source_id="ERP_TRADE_FEED",
        )

        self.adapters.register("ECOS_USD_KRW_DAILY", ecos)
        self.adapters.register("ERP_TRADE_FEED_V1", erp)

        self.assertIs(ecos, self.adapters.get("ECOS_USD_KRW_DAILY"))
        self.assertIs(erp, self.adapters.get("ERP_TRADE_FEED_V1"))

    def test_duplicate_or_mismatched_adapter_is_rejected(self) -> None:
        erp = JsonTradeFeedAdapter(
            endpoint="https://erp.example/trades",
            source_id="ERP_TRADE_FEED",
        )
        self.adapters.register("ERP_TRADE_FEED_V1", erp)
        with self.assertRaisesRegex(ValueError, "already registered"):
            self.adapters.register("ERP_TRADE_FEED_V1", erp)

        wrong_source = JsonTradeFeedAdapter(
            endpoint="https://erp.example/trades",
            source_id="OTHER_SOURCE",
        )
        with self.assertRaisesRegex(ValueError, "source_id"):
            AdapterRegistry(self.datasets).register(
                "ERP_TRADE_FEED_V1", wrong_source
            )


if __name__ == "__main__":
    unittest.main()
