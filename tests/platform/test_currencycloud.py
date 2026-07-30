import json
import io
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.datasets import (
    parse_provider_indicative_forward_quote_payload,
)
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.integration.currencycloud import (
    CurrencycloudDemoForwardQuoteAdapter,
    CurrencycloudError,
)


class Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size=-1):
        return self.raw[:size]


class EmptyResponse(Response):
    def __init__(self):
        self.raw = b""


class CurrencycloudDemoAdapterTests(unittest.TestCase):
    def test_authenticated_future_quote_is_typed_but_not_executable(self) -> None:
        calls = []

        def opener(request, *, timeout):
            calls.append(request)
            if request.full_url.endswith("/v2/authenticate/api"):
                return Response({"auth_token": "session-secret"})
            if request.full_url.endswith("/v2/authenticate/close_session"):
                return EmptyResponse()
            return Response(
                {
                    "currency_pair": "USDKRW",
                    "client_buy_currency": "USD",
                    "client_sell_currency": "KRW",
                    "client_buy_amount": "100000",
                    "client_sell_amount": "139000000",
                    "fixed_side": "buy",
                    "client_rate": "1390",
                    "core_rate": "1389",
                    "mid_market_rate": "1388.5",
                    "conversion_date": "2026-08-28T00:00:00+00:00",
                    "settlement_cut_off_time": "2026-08-28T06:00:00Z",
                }
            )

        adapter = CurrencycloudDemoForwardQuoteAdapter(
            tenant_id="TENANT-1",
            company_id="COMPANY-1",
            login_id="login-secret",
            api_key="api-secret",
            opener=opener,
        )
        payload = adapter.fetch(
            buy_currency="USD",
            sell_currency="KRW",
            amount=Decimal("100000"),
            fixed_side="buy",
            conversion_date=date(2026, 8, 28),
            case_ids=("EXP-1",),
            observed_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
        )
        parsed = parse_provider_indicative_forward_quote_payload(payload)

        self.assertEqual(Decimal("1390"), parsed.records[0].client_rate)
        self.assertEqual("demo", parsed.environment)
        self.assertNotIn("observed_forward_quote", json.dumps(payload))
        self.assertTrue(payload["records"][0]["booking_required"])
        self.assertEqual(
            "session-secret",
            calls[1].get_header("X-auth-token"),
        )
        self.assertTrue(
            calls[2].full_url.endswith("/v2/authenticate/close_session")
        )
        self.assertEqual("session-secret", calls[2].get_header("X-auth-token"))
        self.assertNotIn("secret", repr(adapter))

    def test_collect_never_persists_credentials(self) -> None:
        responses = iter(
            [
                {"auth_token": "session-secret"},
                {
                    "client_buy_currency": "EUR",
                    "client_sell_currency": "GBP",
                    "client_buy_amount": "10000",
                    "client_sell_amount": "8059",
                    "fixed_side": "buy",
                    "client_rate": "0.8059",
                    "core_rate": "0.8058",
                    "mid_market_rate": None,
                    "conversion_date": "2026-08-28",
                },
                {},
            ]
        )
        adapter = CurrencycloudDemoForwardQuoteAdapter(
            tenant_id="TENANT-1",
            company_id="COMPANY-1",
            login_id="login-secret",
            api_key="api-secret",
            opener=lambda request, timeout: Response(next(responses)),
        )
        observed = datetime(2026, 7, 28, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.collect(
                tmp,
                retrieved_at=observed,
                buy_currency="EUR",
                sell_currency="GBP",
                amount="10000",
                fixed_side="buy",
                conversion_date=date(2026, 8, 28),
                case_ids=("EXP-1",),
            )
            _, stored = read_snapshot(path)
        serialized = json.dumps(stored)
        self.assertNotIn("login-secret", serialized)
        self.assertNotIn("api-secret", serialized)
        self.assertNotIn("session-secret", serialized)

    def test_quote_failure_still_closes_session(self) -> None:
        calls = []

        def opener(request, *, timeout):
            calls.append(request)
            if request.full_url.endswith("/v2/authenticate/api"):
                return Response({"auth_token": "session-secret"})
            if request.full_url.endswith("/v2/authenticate/close_session"):
                return Response({})
            raise urllib.error.URLError("offline")

        adapter = CurrencycloudDemoForwardQuoteAdapter(
            tenant_id="TENANT-1",
            company_id="COMPANY-1",
            login_id="login-secret",
            api_key="api-secret",
            opener=opener,
        )
        with self.assertRaisesRegex(CurrencycloudError, "unreachable"):
            adapter.fetch(
                buy_currency="USD",
                sell_currency="EUR",
                amount="1000",
                fixed_side="buy",
                conversion_date=date(2026, 8, 28),
                case_ids=("EXP-1",),
                observed_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            )
        self.assertTrue(
            calls[-1].full_url.endswith("/v2/authenticate/close_session")
        )

    def test_provider_error_preserves_safe_codes_without_request_secrets(self) -> None:
        responses = 0

        def opener(request, *, timeout):
            nonlocal responses
            responses += 1
            if responses == 1:
                return Response({"auth_token": "session-secret"})
            if request.full_url.endswith("/v2/authenticate/close_session"):
                return EmptyResponse()
            body = json.dumps(
                {
                    "error_code": "invalid_currency_pair",
                    "error_messages": {
                        "currency_pair": [
                            {
                                "code": "unsupported",
                                "message": "Pair is unavailable",
                                "params": {
                                    "api_key": "api-secret",
                                    "token": "session-secret",
                                },
                            }
                        ]
                    },
                }
            ).encode("utf-8")
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(body),
            )

        adapter = CurrencycloudDemoForwardQuoteAdapter(
            tenant_id="TENANT-1",
            company_id="COMPANY-1",
            login_id="login-secret",
            api_key="api-secret",
            opener=opener,
        )
        with self.assertRaises(CurrencycloudError) as caught:
            adapter.fetch(
                buy_currency="USD",
                sell_currency="KRW",
                amount="1000",
                fixed_side="buy",
                conversion_date=date(2026, 8, 28),
                case_ids=("EXP-1",),
                observed_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
            )
        message = str(caught.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("invalid_currency_pair", message)
        self.assertIn("currency_pair:unsupported", message)
        self.assertNotIn("api-secret", message)
        self.assertNotIn("session-secret", message)

    def test_missing_credentials_and_non_demo_host_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "official"):
            CurrencycloudDemoForwardQuoteAdapter(
                tenant_id="T",
                company_id="C",
                base_url="https://example.test",
            )
        adapter = CurrencycloudDemoForwardQuoteAdapter(
            tenant_id="T",
            company_id="C",
        )
        with self.assertRaisesRegex(CurrencycloudError, "must be configured"):
            adapter.authenticate()


if __name__ == "__main__":
    unittest.main()
