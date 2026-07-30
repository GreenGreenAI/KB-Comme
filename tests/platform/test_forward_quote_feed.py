import json
import os
import tempfile
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tradeflow.domain.datasets import (
    DatasetContractError,
    ObservedForwardQuoteDataset,
    parse_observed_forward_quote_payload,
    read_observed_forward_quote_snapshot,
)
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.integration.forward_quote_feed import (
    ForwardQuoteFeedError,
    JsonForwardQuoteHistoryAdapter,
)
from tradeflow.tools.forward_quote_history import (
    ForwardQuoteHistoryError,
    OriginSpotRate,
    pair_company_forward_history,
)
from tradeflow.tools.hedge_models import minimum_variance_hedge_ratio


OBSERVED = datetime(2026, 7, 28, tzinfo=UTC)


def payload() -> dict:
    return {
        "schema_version": "1.0",
        "dataset_id": "quotes-20260728-1",
        "tenant_id": "TENANT-1",
        "retention_class": "tenant_private_financial",
        "records": [
            {
                "record_id": "record-1",
                "quote_id": "provider-quote-1",
                "provider_id": "BANK-1",
                "company_id": "COMPANY-1",
                "case_ids": ["EXP-1"],
                "base_currency": "USD",
                "counter_currency": "KRW",
                "side": "sell",
                "notional_min": "10000",
                "notional_max": "500000",
                "contract_rate": "1388.25",
                "cost_rate": "0.0015",
                "settlement_date": "2026-08-31",
                "observed_at": OBSERVED.isoformat(),
                "valid_until": (OBSERVED + timedelta(minutes=5)).isoformat(),
                "quote_basis": "observed_forward_quote",
                "provider_verified": True,
                "company_applicable": True,
                "origin_spot_snapshot": {
                    "source_id": "ECOS_USD_KRW",
                    "version": "2026-07-28",
                    "content_hash": "sha256:" + "a" * 64,
                },
                "evidence_content_hash": "sha256:" + "b" * 64,
                "executed": True,
                "realized_settlement_rate": "1392.10",
                "actual_total_cost": "150.00",
            }
        ],
    }


class Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class ForwardQuotePayloadTests(unittest.TestCase):
    def test_payload_normalizes_decimal_time_scope_and_provenance(self) -> None:
        dataset = parse_observed_forward_quote_payload(payload())

        self.assertIsInstance(dataset, ObservedForwardQuoteDataset)
        self.assertEqual("TENANT-1", dataset.tenant_id)
        self.assertEqual(OBSERVED, dataset.observed_at)
        quote = dataset.records[0]
        self.assertEqual(Decimal("1388.25"), quote.contract_rate)
        self.assertEqual(("EXP-1",), quote.case_ids)
        self.assertEqual("ECOS_USD_KRW", quote.origin_spot_snapshot.source_id)
        self.assertEqual(Decimal("1392.10"), quote.realized_settlement_rate)

    def test_unknown_secret_float_and_unverified_records_fail_closed(self) -> None:
        cases = []
        root_secret = payload()
        root_secret["access_token"] = "must-not-be-stored"
        cases.append((root_secret, "unknown access_token"))
        record_secret = payload()
        record_secret["records"][0]["account_number"] = "123"
        cases.append((record_secret, "unknown account_number"))
        json_float = payload()
        json_float["records"][0]["contract_rate"] = 1388.25
        cases.append((json_float, "decimal string"))
        unverified = payload()
        unverified["records"][0]["provider_verified"] = False
        cases.append((unverified, "provider_verified must be true"))
        cross_company = payload()
        cross_company["records"][0]["company_applicable"] = False
        cases.append((cross_company, "company_applicable must be true"))

        for document, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(DatasetContractError, message):
                    parse_observed_forward_quote_payload(document)

    def test_temporal_notional_currency_and_identity_invariants_are_enforced(self) -> None:
        cases = []
        expired = payload()
        expired["records"][0]["valid_until"] = OBSERVED.isoformat()
        cases.append((expired, "later than observed_at"))
        reversed_notional = payload()
        reversed_notional["records"][0]["notional_max"] = "9999"
        cases.append((reversed_notional, "notional_max"))
        same_currency = payload()
        same_currency["records"][0]["counter_currency"] = "USD"
        cases.append((same_currency, "currencies must differ"))
        duplicate = payload()
        duplicate["records"].append(dict(duplicate["records"][0]))
        cases.append((duplicate, "duplicate forward quote record_id"))

        for document, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(DatasetContractError, message):
                    parse_observed_forward_quote_payload(document)


class ForwardQuotePairingTests(unittest.TestCase):
    @staticmethod
    def _history() -> dict:
        document = payload()
        records = []
        for index, (day, spot_hash, rate) in enumerate(
            (
                (28, "a", "1388.25"),
                (29, "c", "1390.50"),
                (30, "d", "1394.00"),
            ),
            start=1,
        ):
            record = dict(document["records"][0])
            observed = datetime(2026, 7, day, tzinfo=UTC)
            record.update(
                {
                    "record_id": f"record-{index}",
                    "quote_id": f"provider-quote-{index}",
                    "observed_at": observed.isoformat(),
                    "valid_until": (observed + timedelta(minutes=5)).isoformat(),
                    "settlement_date": datetime(
                        2026, 8, day + 1, tzinfo=UTC
                    ).date().isoformat(),
                    "contract_rate": rate,
                    "origin_spot_snapshot": {
                        "source_id": "ECOS_USD_KRW",
                        "version": f"2026-07-{day}",
                        "content_hash": "sha256:" + spot_hash * 64,
                    },
                    "evidence_content_hash": "sha256:" + str(index) * 64,
                }
            )
            records.append(record)
        document["records"] = records
        return document

    def test_exact_scope_and_origin_spot_feed_minimum_variance_model(self) -> None:
        dataset = parse_observed_forward_quote_payload(self._history())
        spot_rates = {
            quote.origin_spot_snapshot: OriginSpotRate(
                quote.observed_at - timedelta(hours=1),
                rate,
            )
            for quote, rate in zip(
                dataset.records,
                (Decimal("1385"), Decimal("1389"), Decimal("1391")),
                strict=True,
            )
        }

        paired = pair_company_forward_history(
            dataset,
            spot_rates,
            company_id="COMPANY-1",
            provider_id="BANK-1",
            base_currency="USD",
            counter_currency="KRW",
            side="sell",
            notional=Decimal("100000"),
            tenor_days=32,
            case_id="EXP-1",
        )
        estimate = minimum_variance_hedge_ratio(
            paired.spot_rates,
            paired.forward_rates,
            window=2,
        )

        self.assertEqual("observed_forward_quote", paired.quote_basis)
        self.assertEqual(2, estimate.observation_count)

    def test_scope_mismatch_missing_spot_and_future_spot_fail_closed(self) -> None:
        dataset = parse_observed_forward_quote_payload(self._history())
        with self.assertRaisesRegex(ForwardQuoteHistoryError, "no company-applicable"):
            pair_company_forward_history(
                dataset,
                {},
                company_id="OTHER-COMPANY",
                provider_id="BANK-1",
                base_currency="USD",
                counter_currency="KRW",
                side="sell",
                notional=Decimal("100000"),
                tenor_days=32,
            )

        with self.assertRaisesRegex(ForwardQuoteHistoryError, "snapshot is unavailable"):
            pair_company_forward_history(
                dataset,
                {},
                company_id="COMPANY-1",
                provider_id="BANK-1",
                base_currency="USD",
                counter_currency="KRW",
                side="sell",
                notional=Decimal("100000"),
                tenor_days=32,
            )

        future_spots = {
            quote.origin_spot_snapshot: OriginSpotRate(
                quote.observed_at + timedelta(seconds=1),
                Decimal("1385"),
            )
            for quote in dataset.records
        }
        with self.assertRaisesRegex(ForwardQuoteHistoryError, "future data"):
            pair_company_forward_history(
                dataset,
                future_spots,
                company_id="COMPANY-1",
                provider_id="BANK-1",
                base_currency="USD",
                counter_currency="KRW",
                side="sell",
                notional=Decimal("100000"),
                tenor_days=32,
            )


class ForwardQuoteAdapterTests(unittest.TestCase):
    def test_https_scope_and_non_secret_repr_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            JsonForwardQuoteHistoryAdapter(
                endpoint="http://connector.example/quotes",
                source_id="PRIVATE_FORWARD_QUOTES",
                tenant_id="TENANT-1",
            )
        adapter = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes?tenant=secret",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="secret-tenant",
            bearer_token="header-secret",
        )
        self.assertNotIn("secret", repr(adapter))

        wrong_tenant = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="TENANT-2",
            opener=lambda request, timeout: Response(
                json.dumps(payload()).encode("utf-8")
            ),
        )
        with self.assertRaisesRegex(ForwardQuoteFeedError, "tenant scope"):
            wrong_tenant.fetch()

    def test_environment_credential_and_private_snapshot_round_trip(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["authorization"] = request.get_header("Authorization")
            return Response(json.dumps(payload()).encode("utf-8"))

        adapter = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="TENANT-1",
            bearer_token_env="TRADEFLOW_TEST_FORWARD_TOKEN",
            opener=opener,
        )
        with patch.dict(
            os.environ,
            {"TRADEFLOW_TEST_FORWARD_TOKEN": "very-secret"},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = adapter.collect(
                    Path(tmp),
                    retrieved_at=OBSERVED + timedelta(minutes=10),
                )
                ref, stored = read_snapshot(path)
                dataset = read_observed_forward_quote_snapshot(
                    path,
                    tenant_id="TENANT-1",
                )

        self.assertEqual("Bearer very-secret", captured["authorization"])
        self.assertEqual("quotes-20260728-1", ref.version)
        self.assertEqual(payload(), stored)
        self.assertNotIn("very-secret", json.dumps(stored))
        self.assertEqual("TENANT-1", dataset.value.tenant_id)

    def test_safe_transport_limits_future_data_and_read_scope(self) -> None:
        def http_error(request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "unauthorized", {}, None
            )

        adapter = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes?token=query-secret",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="TENANT-1",
            bearer_token="header-secret",
            opener=http_error,
        )
        with self.assertRaises(ForwardQuoteFeedError) as caught:
            adapter.fetch()
        self.assertEqual(
            "forward quote feed returned HTTP 401",
            str(caught.exception),
        )
        self.assertNotIn("secret", str(caught.exception))

        oversized = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="TENANT-1",
            max_bytes=4,
            opener=lambda request, timeout: Response(b"12345"),
        )
        with self.assertRaisesRegex(ForwardQuoteFeedError, "size limit"):
            oversized.fetch()

        future = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="TENANT-1",
            opener=lambda request, timeout: Response(
                json.dumps(payload()).encode("utf-8")
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ForwardQuoteFeedError, "later than"):
                future.collect(tmp, retrieved_at=OBSERVED - timedelta(seconds=1))

        valid = JsonForwardQuoteHistoryAdapter(
            endpoint="https://connector.example/quotes",
            source_id="PRIVATE_FORWARD_QUOTES",
            tenant_id="TENANT-1",
            opener=lambda request, timeout: Response(
                json.dumps(payload()).encode("utf-8")
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = valid.collect(
                tmp,
                retrieved_at=OBSERVED + timedelta(minutes=10),
            )
            with self.assertRaisesRegex(DatasetContractError, "tenant scope"):
                read_observed_forward_quote_snapshot(
                    path,
                    tenant_id="TENANT-2",
                )


if __name__ == "__main__":
    unittest.main()
