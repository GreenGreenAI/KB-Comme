import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tradeflow.domain.dataset_registry import (
    DatasetRegistry,
    default_parser_registry,
)
from tradeflow.domain.datasets import (
    DatasetContractError,
    ReferenceFxCatalog,
    parse_koreaexim_reference_fx_payload,
)
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.integration.koreaexim_fx import (
    KoreaEximFxAdapter,
    KoreaEximFxError,
)
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot


ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))


def row(
    currency_unit: str = "USD",
    *,
    deal_base_rate: str = "1,320.50",
    result: int = 1,
) -> dict:
    values = {
        "result": result,
        "cur_unit": currency_unit,
        "ttb": "1,307.29",
        "tts": "1,333.71",
        "deal_bas_r": deal_base_rate,
        "bkpr": "1,320",
        "yy_efee_r": "0",
        "ten_dd_efee_r": "0",
        "kftc_bkpr": "1,320",
        "kftc_deal_bas_r": deal_base_rate,
        "cur_nm": "미국 달러",
    }
    if result != 1:
        return {field: (result if field == "result" else None) for field in values}
    return values


def wrapper(*records: dict) -> dict:
    return {
        "schema_version": "1.0",
        "search_date": "2026-07-27",
        "response": list(records or (row(),)),
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


class KoreaEximFxParserTests(unittest.TestCase):
    def test_multi_currency_units_and_comma_decimals_are_preserved(self) -> None:
        usd = row()
        jpy = row("JPY(100)", deal_base_rate="912.34")
        jpy["cur_nm"] = "일본 옌"
        catalog = parse_koreaexim_reference_fx_payload(wrapper(usd, jpy))

        self.assertIsInstance(catalog, ReferenceFxCatalog)
        self.assertEqual(date(2026, 7, 27), catalog.observed_on)
        self.assertEqual(Decimal("1320.50"), catalog.get("usd").deal_base_rate)
        self.assertEqual(100, catalog.get("JPY").currency_unit)
        self.assertEqual(
            Decimal("9.1234"), catalog.get("JPY").krw_per_currency_unit
        )
        with self.assertRaises(TypeError):
            catalog.rates["EUR"] = catalog.get("USD")

    def test_http_success_with_official_error_result_is_a_failure(self) -> None:
        for result, message in (
            (2, "DATA code error"),
            (3, "authentication code error"),
            (4, "daily request limit exhausted"),
            (9, "unknown result code 9"),
        ):
            with self.subTest(result=result):
                with self.assertRaisesRegex(DatasetContractError, message):
                    parse_koreaexim_reference_fx_payload(
                        wrapper(row(result=result))
                    )

    def test_partial_ambiguous_or_invalid_rates_fail_closed(self) -> None:
        cases = []
        missing = row()
        del missing["deal_bas_r"]
        cases.append((wrapper(missing), "missing deal_bas_r"))
        unknown = row()
        unknown["unexpected"] = "value"
        cases.append((wrapper(unknown), "unknown unexpected"))
        malformed_unit = row("JPY(x100)")
        cases.append((wrapper(malformed_unit), "cur_unit is invalid"))
        zero = row(deal_base_rate="0")
        cases.append((wrapper(zero), "must be positive"))
        negative = row()
        negative["ttb"] = "-1"
        cases.append((wrapper(negative), "must not be negative"))
        numeric_drift = row()
        numeric_drift["ttb"] = 1307.29
        cases.append((wrapper(numeric_drift), "must be a decimal string"))
        duplicate = wrapper(row("JPY"), row("JPY(100)"))
        cases.append((duplicate, "duplicate Korea Eximbank currency"))
        empty = wrapper()
        empty["response"] = []
        cases.append((empty, "must be non-empty"))
        extra_root = wrapper()
        extra_root["authkey"] = "must-not-be-stored"
        cases.append((extra_root, "requires only"))

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(DatasetContractError, message):
                    parse_koreaexim_reference_fx_payload(payload)


class KoreaEximFxAdapterTests(unittest.TestCase):
    def test_request_uses_new_domain_ap01_and_does_not_expose_key(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response(json.dumps([row()]).encode("utf-8"))

        adapter = KoreaEximFxAdapter(api_key="very-secret", opener=opener)
        catalog, payload = adapter.fetch(search_date=date(2026, 7, 27))

        parsed = urllib.parse.urlsplit(captured["url"])
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual("oapi.koreaexim.go.kr", parsed.hostname)
        self.assertEqual(["very-secret"], query["authkey"])
        self.assertEqual(["20260727"], query["searchdate"])
        self.assertEqual(["AP01"], query["data"])
        self.assertEqual(30, captured["timeout"])
        self.assertEqual(Decimal("1320.50"), catalog.get("USD").deal_base_rate)
        self.assertNotIn("very-secret", json.dumps(payload))
        self.assertNotIn("very-secret", repr(adapter))

    def test_safe_errors_and_response_limits(self) -> None:
        def http_error(request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "unauthorized", {}, None
            )

        adapter = KoreaEximFxAdapter(
            api_key="header-secret",
            opener=http_error,
        )
        with self.assertRaises(KoreaEximFxError) as caught:
            adapter.fetch(search_date=date(2026, 7, 27))
        self.assertEqual("Korea Eximbank returned HTTP 401", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

        oversized = KoreaEximFxAdapter(
            api_key="key",
            max_bytes=4,
            opener=lambda request, timeout: Response(b"12345"),
        )
        with self.assertRaisesRegex(KoreaEximFxError, "size limit"):
            oversized.fetch(search_date=date(2026, 7, 27))

        official_error = KoreaEximFxAdapter(
            api_key="bad-key",
            opener=lambda request, timeout: Response(
                json.dumps([row(result=3)]).encode("utf-8")
            ),
        )
        with self.assertRaisesRegex(KoreaEximFxError, "authentication code"):
            official_error.fetch(search_date=date(2026, 7, 27))

    def test_collect_preserves_response_without_authkey_and_registry_reads_it(self) -> None:
        adapter = KoreaEximFxAdapter(
            api_key="very-secret",
            opener=lambda request, timeout: Response(
                json.dumps([row(), row("JPY(100)", deal_base_rate="912.34")]).encode(
                    "utf-8"
                )
            ),
        )
        retrieved = datetime(2026, 7, 27, 1, tzinfo=UTC)
        registry = DatasetRegistry.from_json(ROOT / "data" / "dataset_registry.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.collect(
                tmp,
                search_date=date(2026, 7, 27),
                retrieved_at=retrieved,
            )
            ref, stored = read_snapshot(path)
            dataset = registry.read_snapshot(
                "KOREAEXIM_REFERENCE_FX_DAILY",
                path,
                parsers=default_parser_registry(),
                evaluated_at=retrieved,
            )

        self.assertEqual("KOREAEXIM_REFERENCE_FX", ref.source_id)
        self.assertEqual(datetime(2026, 7, 27, tzinfo=KST), ref.observed_at)
        self.assertNotIn("authkey", json.dumps(stored))
        self.assertIsInstance(dataset.value, ReferenceFxCatalog)
        self.assertEqual(Decimal("9.1234"), dataset.value.get("JPY").krw_per_currency_unit)

    def test_endpoint_key_and_future_date_contracts_are_strict(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            KoreaEximFxAdapter(endpoint="http://example.test", api_key="key")
        with self.assertRaisesRegex(ValueError, "query or fragment"):
            KoreaEximFxAdapter(
                endpoint="https://example.test?authkey=embedded",
                api_key="key",
            )
        with patch.dict(os.environ, {"KOREAEXIM_API_KEY": ""}):
            with self.assertRaisesRegex(KoreaEximFxError, "is not set"):
                KoreaEximFxAdapter(api_key=None).fetch(
                    search_date=date(2026, 7, 27)
                )
        with self.assertRaisesRegex(TypeError, "must be a date"):
            KoreaEximFxAdapter(api_key="key").fetch(
                search_date=datetime(2026, 7, 27, tzinfo=UTC)
            )
        adapter = KoreaEximFxAdapter(
            api_key="key",
            opener=lambda request, timeout: Response(
                json.dumps([row()]).encode("utf-8")
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(KoreaEximFxError, "later than"):
                adapter.collect(
                    tmp,
                    search_date=date(2026, 7, 27),
                    retrieved_at=datetime(2026, 7, 26, tzinfo=UTC),
                )

    def test_registry_rejects_search_date_and_snapshot_date_mismatch(self) -> None:
        registry = DatasetRegistry.from_json(ROOT / "data" / "dataset_registry.json")
        at = datetime(2026, 7, 28, 1, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_snapshot(
                tmp,
                build_envelope(
                    source_id="KOREAEXIM_REFERENCE_FX",
                    version="mismatched-date",
                    observed_at=datetime(2026, 7, 28, tzinfo=KST),
                    retrieved_at=at,
                    payload=wrapper(row()),
                ),
            )
            with self.assertRaisesRegex(
                DatasetContractError,
                "search_date does not match",
            ):
                registry.read_snapshot(
                    "KOREAEXIM_REFERENCE_FX_DAILY",
                    path,
                    parsers=default_parser_registry(),
                    evaluated_at=at,
                )


if __name__ == "__main__":
    unittest.main()
