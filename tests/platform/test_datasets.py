import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.datasets import (
    DatasetContractError,
    FxSeries,
    StaleDatasetError,
    TradeFeedData,
    read_ecos_usd_krw_snapshot,
    read_trade_feed_snapshot,
    trade_program_from_snapshot,
)
from tradeflow.domain.models import CompanyProfile
from tradeflow.domain.snapshot import FreshnessPolicy
from tradeflow.domain.snapshot_file import (
    SnapshotNotFoundError,
    latest_snapshot_path,
    list_snapshot_refs,
)
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot

KST = timezone(timedelta(hours=9))


def _trade_payload(
    *,
    version: str = "erp-20260727-090000",
    observed_at: str = "2026-07-27T09:00:00+09:00",
) -> dict:
    return {
        "schema_version": "1.0",
        "version": version,
        "observed_at": observed_at,
        "opening_balances": {"USD": "1200.50"},
        "trades": [
            {
                "case_id": "EXP-1",
                "direction": "export",
                "currency": "USD",
                "amount": "10000.25",
                "expected_payment_date": "2026-08-31",
                "payment_method": "tt",
            }
        ],
    }


def _write_trade_snapshot(root: Path, payload: dict) -> Path:
    observed = datetime.fromisoformat(payload["observed_at"])
    return write_snapshot(
        root,
        build_envelope(
            source_id="ERP_TRADE_FEED",
            version=payload["version"],
            observed_at=observed,
            retrieved_at=observed + timedelta(minutes=1),
            payload=payload,
        ),
    )


class TradeDatasetTests(unittest.TestCase):
    def test_snapshot_becomes_a_program_with_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_trade_snapshot(Path(tmp), _trade_payload())
            dataset = read_trade_feed_snapshot(
                path,
                freshness_policy=FreshnessPolicy(timedelta(hours=2)),
                evaluated_at=datetime(2026, 7, 27, 9, 30, tzinfo=KST),
            )
            program = trade_program_from_snapshot(
                dataset,
                program_id="P1",
                company=CompanyProfile("C1", "Exporter"),
                as_of=date(2026, 7, 27),
            )

        self.assertIsInstance(dataset.value, TradeFeedData)
        self.assertEqual(Decimal("10000.25"), program.cases[0].amount)
        self.assertEqual(Decimal("1200.50"), program.opening_balances["USD"])
        self.assertEqual((dataset.ref,), program.input_snapshots)

    def test_stale_trade_snapshot_is_not_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_trade_snapshot(Path(tmp), _trade_payload())
            with self.assertRaises(StaleDatasetError):
                read_trade_feed_snapshot(
                    path,
                    freshness_policy=FreshnessPolicy(timedelta(minutes=10)),
                    evaluated_at=datetime(2026, 7, 27, 10, 0, tzinfo=KST),
                )

    def test_payload_and_envelope_identity_must_agree(self) -> None:
        payload = _trade_payload(version="payload-v1")
        observed = datetime.fromisoformat(payload["observed_at"])
        with tempfile.TemporaryDirectory() as tmp:
            path = write_snapshot(
                tmp,
                build_envelope(
                    source_id="ERP_TRADE_FEED",
                    version="envelope-v1",
                    observed_at=observed,
                    retrieved_at=observed,
                    payload=payload,
                ),
            )
            with self.assertRaisesRegex(DatasetContractError, "does not match"):
                read_trade_feed_snapshot(
                    path,
                    freshness_policy=FreshnessPolicy(timedelta(days=1)),
                    evaluated_at=observed,
                )


class EcosDatasetTests(unittest.TestCase):
    def test_committed_ecos_snapshot_is_normalized(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = root / "data" / "snapshots" / "ECOS_USD_KRW" / "2026-07-24.json"

        dataset = read_ecos_usd_krw_snapshot(
            path,
            freshness_policy=FreshnessPolicy(timedelta(days=4)),
            evaluated_at=datetime(2026, 7, 27, tzinfo=KST),
        )

        self.assertIsInstance(dataset.value, FxSeries)
        self.assertEqual("USD", dataset.value.base_currency)
        self.assertEqual("KRW", dataset.value.quote_currency)
        self.assertEqual(date(2026, 7, 24), dataset.value.latest.observed_on)
        self.assertGreater(len(dataset.value.observations), 2500)


class SnapshotCatalogTests(unittest.TestCase):
    def test_latest_uses_observation_time_not_lexical_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = _trade_payload(
                version="z-old",
                observed_at="2026-07-26T09:00:00+09:00",
            )
            newer = _trade_payload(
                version="a-new",
                observed_at="2026-07-27T09:00:00+09:00",
            )
            _write_trade_snapshot(root, older)
            expected = _write_trade_snapshot(root, newer)

            refs = list_snapshot_refs(root, "ERP_TRADE_FEED")

            self.assertEqual(2, len(refs))
            self.assertEqual(expected, latest_snapshot_path(root, "ERP_TRADE_FEED"))

    def test_missing_source_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SnapshotNotFoundError):
                latest_snapshot_path(tmp, "MISSING")


if __name__ == "__main__":
    unittest.main()
