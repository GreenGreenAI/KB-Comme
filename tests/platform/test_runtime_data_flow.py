import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tradeflow.domain.dataset_registry import (
    DatasetRegistry,
    default_parser_registry,
)
from tradeflow.domain.datasets import trade_program_from_snapshot
from tradeflow.domain.models import CompanyProfile
from tradeflow.domain.snapshot_file import latest_snapshot_path
from tradeflow.integration.registry import AdapterRegistry
from tradeflow.integration.trade_feed import JsonTradeFeedAdapter
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


class RuntimeDataFlowTests(unittest.TestCase):
    def test_api_to_decision_packet_preserves_snapshot_identity(self) -> None:
        payload = {
            "schema_version": "1.0",
            "version": "erp-20260727-090000",
            "observed_at": "2026-07-27T09:00:00+09:00",
            "opening_balances": {"USD": "20000"},
            "trades": [
                {
                    "case_id": "IMPORT-1",
                    "direction": "import",
                    "currency": "USD",
                    "amount": "60000",
                    "expected_payment_date": "2026-08-25",
                    "payment_method": "tt",
                },
                {
                    "case_id": "EXPORT-1",
                    "direction": "export",
                    "currency": "USD",
                    "amount": "100000",
                    "expected_payment_date": "2026-10-24",
                    "payment_method": "tt",
                },
            ],
        }
        adapter = JsonTradeFeedAdapter(
            endpoint="https://erp.example/trades",
            source_id="ERP_TRADE_FEED",
            opener=lambda request, timeout: _Response(payload),
        )
        datasets = DatasetRegistry.from_json(
            ROOT / "data" / "dataset_registry.json"
        )
        adapters = AdapterRegistry(datasets)
        adapters.register("ERP_TRADE_FEED_V1", adapter)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapters.get("ERP_TRADE_FEED_V1").collect(
                root,
                retrieved_at=datetime(2026, 7, 27, 9, 1, tzinfo=KST),
            )
            path = latest_snapshot_path(root, "ERP_TRADE_FEED")
            dataset = datasets.read_snapshot(
                "ERP_TRADE_FEED_V1",
                path,
                parsers=default_parser_registry(),
                evaluated_at=datetime(2026, 7, 27, 9, 30, tzinfo=KST),
            )
            program = trade_program_from_snapshot(
                dataset,
                program_id="P1",
                company=CompanyProfile("C1", "Exporter"),
                as_of=date(2026, 7, 27),
            )
            packet = TradeFlowPipeline(
                KnowledgeRepository((), ())
            ).analyze_packet(program)

        exposure = packet.exposures[0]
        self.assertEqual("40000", str(exposure.trade_net_exposure))
        self.assertEqual("40000", str(exposure.peak_funding_gap))
        self.assertEqual(("ERP_TRADE_FEED",), packet.evidence[0].source_ids)
        snapshot = dict(packet.evidence[0].payload)["snapshots"][0]
        self.assertEqual("erp-20260727-090000", dict(snapshot)["version"])
        self.assertEqual(dataset.ref.content_hash, dict(snapshot)["content_hash"])


if __name__ == "__main__":
    unittest.main()
