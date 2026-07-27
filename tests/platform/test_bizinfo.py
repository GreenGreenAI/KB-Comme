import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tradeflow.domain.dataset_registry import (
    DatasetRegistry,
    default_parser_registry,
)
from tradeflow.domain.datasets import (
    DatasetContractError,
    SupportProgramCatalog,
    parse_bizinfo_support_payload,
)
from tradeflow.domain.snapshot_file import latest_snapshot_path
from tradeflow.integration.bizinfo import (
    API_KEY_ENV,
    BizinfoError,
    BizinfoSupportAdapter,
)

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))


def _payload() -> dict:
    return {
        "jsonArray": {
            "item": [
                {
                    "pblancId": "BIZ-100",
                    "pblancNm": "수출 중소기업 정책자금",
                    "jrsdInsttNm": "중소벤처기업부",
                    "excInsttNm": "중소벤처기업진흥공단",
                    "pldirSportRealmLclasCodeNm": "금융",
                    "trgetNm": "수출 중소기업",
                    "bsnsSumryCn": "운전자금 지원",
                    "reqstBeginEndDe": "2026-07-01 ~ 2026-07-31",
                    "pblancUrl": "https://www.bizinfo.go.kr/example/BIZ-100",
                    "hashTags": "수출, 정책자금",
                    "creatPnttm": "2026-07-01 09:30:00",
                    "totCnt": "1",
                }
            ]
        }
    }


class _Response:
    def __init__(self, payload: dict | bytes) -> None:
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class BizinfoParserTests(unittest.TestCase):
    def test_official_fields_are_normalized_without_llm_inference(self) -> None:
        catalog = parse_bizinfo_support_payload(_payload())

        self.assertEqual(1, catalog.total_count)
        program = catalog.programs[0]
        self.assertEqual("BIZ-100", program.program_id)
        self.assertEqual("중소벤처기업부", program.authority)
        self.assertEqual("중소벤처기업진흥공단", program.executing_agency)
        self.assertEqual(("수출", "정책자금"), program.hashtags)
        self.assertEqual(datetime(2026, 7, 1, 9, 30), program.published_at)

    def test_single_item_object_and_documented_aliases_are_supported(self) -> None:
        payload = {
            "jsonArray": {
                "item": {
                    "seq": "10",
                    "title": "지원 공고",
                    "author": "기관",
                    "lcategory": "수출",
                    "trgetNm": "중소기업",
                    "link": "https://www.bizinfo.go.kr/10",
                    "pubDate": "2026-07-01",
                }
            }
        }

        catalog = parse_bizinfo_support_payload(payload)

        self.assertEqual("10", catalog.programs[0].program_id)
        self.assertEqual(1, catalog.total_count)

    def test_duplicate_ids_and_invalid_totals_are_rejected(self) -> None:
        duplicate = _payload()
        duplicate["jsonArray"]["item"].append(
            dict(duplicate["jsonArray"]["item"][0])
        )
        with self.assertRaisesRegex(DatasetContractError, "duplicate"):
            parse_bizinfo_support_payload(duplicate)

        invalid_total = _payload()
        invalid_total["jsonArray"]["item"][0]["totCnt"] = "none"
        with self.assertRaisesRegex(DatasetContractError, "totCnt"):
            parse_bizinfo_support_payload(invalid_total)


class BizinfoAdapterTests(unittest.TestCase):
    def test_fetch_uses_official_query_contract_and_keeps_key_out_of_repr(self) -> None:
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["accept"] = request.get_header("Accept")
            captured["timeout"] = timeout
            return _Response(_payload())

        adapter = BizinfoSupportAdapter(
            api_key="very-secret", opener=opener, timeout=12
        )
        result = adapter.fetch(
            category_code="02", hashtags=("수출", "금융"), page_size=25, page_index=2
        )

        query = urllib.parse.parse_qs(urllib.parse.urlsplit(captured["url"]).query)
        self.assertEqual(["very-secret"], query["crtfcKey"])
        self.assertEqual(["json"], query["dataType"])
        self.assertEqual(["02"], query["searchLclasId"])
        self.assertEqual(["수출,금융"], query["hashtags"])
        self.assertEqual(["25"], query["pageUnit"])
        self.assertEqual(["2"], query["pageIndex"])
        self.assertEqual("application/json", captured["accept"])
        self.assertEqual(12, captured["timeout"])
        self.assertEqual(_payload(), result)
        self.assertNotIn("very-secret", repr(adapter))

    def test_missing_key_transport_failures_and_bad_payload_are_safe_errors(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(BizinfoError, API_KEY_ENV):
                BizinfoSupportAdapter().fetch()

        def http_error(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "", {}, None)

        with self.assertRaisesRegex(BizinfoError, "HTTP 403"):
            BizinfoSupportAdapter(api_key="secret", opener=http_error).fetch()

        with self.assertRaisesRegex(BizinfoError, "valid UTF-8 JSON"):
            BizinfoSupportAdapter(
                api_key="secret", opener=lambda request, timeout: _Response(b"not-json")
            ).fetch()

    def test_size_limit_and_endpoint_validation_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            BizinfoSupportAdapter(api_key="secret", endpoint="http://example.com")
        with self.assertRaisesRegex(ValueError, "source_id"):
            BizinfoSupportAdapter(api_key="secret", source_id="../escape")
        with self.assertRaisesRegex(BizinfoError, "size limit"):
            BizinfoSupportAdapter(
                api_key="secret",
                max_bytes=3,
                opener=lambda request, timeout: _Response(b"1234"),
            ).fetch()

    def test_collect_round_trip_through_declarative_registry(self) -> None:
        retrieved = datetime(2026, 7, 27, 9, tzinfo=KST)
        adapter = BizinfoSupportAdapter(
            api_key="secret",
            opener=lambda request, timeout: _Response(_payload()),
        )
        registry = DatasetRegistry.from_json(ROOT / "data" / "dataset_registry.json")

        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.collect(tmp, retrieved_at=retrieved)
            self.assertEqual(
                path,
                latest_snapshot_path(tmp, "BIZINFO_SUPPORT_API"),
            )
            dataset = registry.read_snapshot(
                "BIZINFO_SUPPORT_PROGRAMS_DAILY",
                path,
                parsers=default_parser_registry(),
                evaluated_at=retrieved + timedelta(hours=1),
            )

        self.assertIsInstance(dataset.value, SupportProgramCatalog)
        self.assertEqual("BIZ-100", dataset.value.programs[0].program_id)
        self.assertEqual("BIZINFO_SUPPORT_API", dataset.ref.source_id)


if __name__ == "__main__":
    unittest.main()
