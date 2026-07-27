import json
import tempfile
import unittest
import urllib.error
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.integration.trade_feed import (
    JsonTradeFeedAdapter,
    TradeFeedError,
    parse_trade_feed,
)


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "version": "erp-20260727-090000",
        "observed_at": "2026-07-27T09:00:00+09:00",
        "opening_balances": {"usd": "1200.50"},
        "trades": [
            {
                "case_id": "EXP-1",
                "direction": "export",
                "currency": "usd",
                "amount": "10000.25",
                "expected_payment_date": "2026-08-31",
                "payment_method": "tt",
                "counterparty_country": "US",
                "confirmed": True,
                "attributes": {"erp_document_id": "9001"},
            }
        ],
    }


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class ParseTradeFeedTests(unittest.TestCase):
    def test_values_are_normalized_to_domain_types(self) -> None:
        batch = parse_trade_feed(_payload())

        case = batch.cases[0]
        self.assertEqual(TradeDirection.EXPORT, case.direction)
        self.assertEqual("USD", case.currency)
        self.assertEqual(Decimal("10000.25"), case.amount)
        self.assertEqual(PaymentMethod.TT, case.payment_method)
        self.assertEqual(Decimal("1200.50"), batch.opening_balances["USD"])

    def test_duplicate_case_ids_are_refused(self) -> None:
        payload = _payload()
        payload["trades"].append(dict(payload["trades"][0]))

        with self.assertRaisesRegex(TradeFeedError, "duplicate case_id"):
            parse_trade_feed(payload)

    def test_unknown_schema_is_refused(self) -> None:
        payload = _payload()
        payload["schema_version"] = "2.0"

        with self.assertRaisesRegex(TradeFeedError, "unsupported schema_version"):
            parse_trade_feed(payload)

    def test_timezone_is_required(self) -> None:
        payload = _payload()
        payload["observed_at"] = "2026-07-27T09:00:00"

        with self.assertRaisesRegex(TradeFeedError, "time zone"):
            parse_trade_feed(payload)

    def test_non_positive_amount_is_refused_by_domain_model(self) -> None:
        payload = _payload()
        payload["trades"][0]["amount"] = "0"

        with self.assertRaisesRegex(TradeFeedError, "positive"):
            parse_trade_feed(payload)


class JsonTradeFeedAdapterTests(unittest.TestCase):
    def test_https_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            JsonTradeFeedAdapter(
                endpoint="http://erp.example/feed", source_id="ERP_TRADE_FEED"
            )

    def test_bearer_header_is_sent_but_not_exposed(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return _Response(json.dumps(_payload()).encode())

        adapter = JsonTradeFeedAdapter(
            endpoint="https://erp.example/feed?tenant=one",
            source_id="ERP_TRADE_FEED",
            bearer_token="very-secret",
            opener=opener,
        )

        adapter.fetch()

        self.assertEqual("Bearer very-secret", captured["authorization"])
        self.assertEqual(30, captured["timeout"])
        self.assertNotIn("very-secret", repr(adapter))

    def test_http_error_does_not_leak_endpoint_or_token(self) -> None:
        def opener(request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "unauthorized", {}, None
            )

        adapter = JsonTradeFeedAdapter(
            endpoint="https://erp.example/feed?api_key=query-secret",
            source_id="ERP_TRADE_FEED",
            bearer_token="header-secret",
            opener=opener,
        )

        with self.assertRaises(TradeFeedError) as caught:
            adapter.fetch()

        message = str(caught.exception)
        self.assertEqual("trade feed returned HTTP 401", message)
        self.assertNotIn("secret", message)

    def test_oversized_response_is_refused(self) -> None:
        adapter = JsonTradeFeedAdapter(
            endpoint="https://erp.example/feed",
            source_id="ERP_TRADE_FEED",
            max_bytes=8,
            opener=lambda request, timeout: _Response(b"123456789"),
        )

        with self.assertRaisesRegex(TradeFeedError, "response limit"):
            adapter.fetch()

    def test_collect_preserves_raw_payload_in_snapshot(self) -> None:
        payload = _payload()
        adapter = JsonTradeFeedAdapter(
            endpoint="https://erp.example/feed",
            source_id="ERP_TRADE_FEED",
            opener=lambda request, timeout: _Response(json.dumps(payload).encode()),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.collect(
                Path(tmp),
                retrieved_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
            )
            ref, stored = read_snapshot(path)

        self.assertEqual("ERP_TRADE_FEED", ref.source_id)
        self.assertEqual("erp-20260727-090000", ref.version)
        self.assertEqual(payload, stored)

    def test_future_observation_is_refused(self) -> None:
        adapter = JsonTradeFeedAdapter(
            endpoint="https://erp.example/feed",
            source_id="ERP_TRADE_FEED",
            opener=lambda request, timeout: _Response(
                json.dumps(_payload()).encode()
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(TradeFeedError, "later than"):
                adapter.collect(
                    tmp,
                    retrieved_at=datetime(2026, 7, 26, tzinfo=UTC),
                )


if __name__ == "__main__":
    unittest.main()
