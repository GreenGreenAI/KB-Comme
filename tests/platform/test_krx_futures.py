import json
import unittest
from datetime import date

from tradeflow.domain.datasets import parse_listed_fx_futures_daily_payload
from tradeflow.integration.krx_futures import KrxFuturesError, KrxUsdFuturesAdapter


class Response:
    def __init__(self, payload):
        self.raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, size=-1):
        return self.raw[:size]


def raw_payload(product_name="미국달러 선물"):
    return {
        "OutBlock_1": [
            {
                "BAS_DD": "20260727",
                "PROD_NM": product_name,
                "MKT_NM": "정규",
                "ISU_CD": "175Q8000",
                "ISU_NM": "미국달러 F 202608",
                "TDD_CLSPRC": "1,389.50",
                "SETL_PRC": "1,389.60",
                "SPOT_PRC": "1,388.20",
                "ACC_TRDVOL": "12,345",
                "ACC_OPNINT_QTY": "45,678",
            }
        ]
    }


class KrxUsdFuturesAdapterTests(unittest.TestCase):
    def test_actual_krx_shape_becomes_listed_benchmark_only(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["key"] = request.get_header("Auth_key")
            captured["url"] = request.full_url
            return Response(raw_payload())

        adapter = KrxUsdFuturesAdapter(api_key="key-secret", opener=opener)
        payload = adapter.fetch(date(2026, 7, 27))
        parsed = parse_listed_fx_futures_daily_payload(payload)
        record = parsed.records[0]

        self.assertEqual("listed_fx_future", parsed.benchmark_class)
        self.assertEqual("1389.50", str(record.close_price))
        self.assertEqual(12345, record.volume)
        self.assertEqual("key-secret", captured["key"])
        self.assertIn("basDd=20260727", captured["url"])
        self.assertNotIn("observed_forward_quote", json.dumps(payload))

    def test_no_usd_future_and_wrong_host_fail_closed(self) -> None:
        adapter = KrxUsdFuturesAdapter(
            api_key="key",
            opener=lambda request, timeout: Response(raw_payload("코스피200 선물")),
        )
        with self.assertRaisesRegex(KrxFuturesError, "no USD futures"):
            adapter.fetch(date(2026, 7, 27))
        with self.assertRaisesRegex(ValueError, "official"):
            KrxUsdFuturesAdapter(endpoint="https://example.test/api")


if __name__ == "__main__":
    unittest.main()
