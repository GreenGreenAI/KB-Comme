import json
import tempfile
import unittest
import urllib.error
from datetime import UTC, date, datetime
from pathlib import Path

from tradeflow.domain.datasets import (
    DatasetContractError,
    KsureCountryPolicyCatalog,
    SnapshotDataset,
    parse_ksure_country_policy_payload,
)
from tradeflow.domain.enums import (
    CountryPolicyStatus,
    PaymentMethod,
    TradeDirection,
)
from tradeflow.domain.models import TradeCase
from tradeflow.domain.snapshot import SnapshotRef
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.integration.ksure_country_policy import (
    KsureCountryPolicyAdapter,
    KsureCountryPolicyError,
)
from tradeflow.knowledge.facts import FactContractError
from tradeflow.knowledge.ksure import KsureCaseProfile, bind_country_policy


def _filter_record(code: str) -> dict:
    return {"ggCode": code, "trgtpsnNm": f"Country {code}"}


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "directory": {
            "getNationLst": [
                {"stdInfrmCtryCd": code, "trgtpsnNm": f"Country {code}"}
                for code in ("US", "TR", "SY", "MF")
            ]
        },
        "policy_filters": {
            "normal": {"selectFilterLst": [_filter_record("US")]},
            "conditional": {"selectFilterLst": [_filter_record("TR")]},
            "restricted": {"selectFilterLst": [_filter_record("SY")]},
            "deep_watch": {"selectFilterLst": [_filter_record("TR")]},
        },
    }


def _response_for(request) -> "_Response":
    payload = _payload()
    if request.full_url.endswith("getAutoLst"):
        document = payload["directory"]
    else:
        body = json.loads(request.data.decode("utf-8"))
        key = next(
            name
            for marker, name in (
                ("insuChkFlag1", "normal"),
                ("jogunRiskFlag", "conditional"),
                ("highRishFlag1", "restricted"),
                ("depWatchFlag1", "deep_watch"),
            )
            if marker in body
        )
        document = payload["policy_filters"][key]
    return _Response(json.dumps(document).encode("utf-8"))


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class KsureCountryPolicyParserTests(unittest.TestCase):
    def test_flags_become_typed_country_policies(self) -> None:
        catalog = parse_ksure_country_policy_payload(_payload())

        self.assertIsInstance(catalog, KsureCountryPolicyCatalog)
        self.assertEqual(CountryPolicyStatus.NORMAL, catalog.get("us").status)
        self.assertEqual(
            CountryPolicyStatus.CONDITIONAL, catalog.get("TR").status
        )
        self.assertTrue(catalog.get("TR").deep_watch)
        self.assertTrue(catalog.get("SY").country_restricted)
        self.assertFalse(catalog.get("TR").country_restricted)
        self.assertEqual(CountryPolicyStatus.UNKNOWN, catalog.get("MF").status)
        with self.assertRaisesRegex(DatasetContractError, "unknown for MF"):
            catalog.get("MF").country_restricted
        with self.assertRaises(TypeError):
            catalog.policies["KR"] = catalog.get("US")

    def test_unknown_missing_duplicate_and_inconsistent_flags_fail_closed(self) -> None:
        duplicate_directory = _payload()
        duplicate_directory["directory"]["getNationLst"].append(
            {"stdInfrmCtryCd": "US", "trgtpsnNm": "Duplicate"}
        )
        unknown_filter = _payload()
        unknown_filter["policy_filters"]["normal"]["selectFilterLst"] = [
            _filter_record("ZZ")
        ]
        duplicate_filter = _payload()
        duplicate_filter["policy_filters"]["normal"]["selectFilterLst"] *= 2
        empty_restricted = _payload()
        empty_restricted["policy_filters"]["restricted"]["selectFilterLst"] = []
        malformed = (
            {},
            {**_payload(), "schema_version": "2.0"},
            {**_payload(), "directory": {"getNationLst": []}},
            duplicate_directory,
            unknown_filter,
            duplicate_filter,
            empty_restricted,
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(DatasetContractError):
                    parse_ksure_country_policy_payload(payload)

        with self.assertRaisesRegex(KeyError, "unavailable for ZZ"):
            parse_ksure_country_policy_payload(_payload()).get("ZZ")


class KsureCountryPolicyAdapterTests(unittest.TestCase):
    def test_official_post_contract_is_used_and_payload_is_validated(self) -> None:
        captured = []

        def opener(request, *, timeout):
            captured.append(
                {
                    "method": request.get_method(),
                    "body": json.loads(request.data.decode("utf-8")),
                    "referer": request.get_header("Referer"),
                    "timeout": timeout,
                }
            )
            return _response_for(request)

        adapter = KsureCountryPolicyAdapter(opener=opener)
        payload = adapter.fetch()

        self.assertEqual(5, len(captured))
        self.assertTrue(all(item["method"] == "POST" for item in captured))
        self.assertEqual({}, captured[0]["body"])
        self.assertIn("highRishFlag1", captured[3]["body"])
        self.assertIn("ksight.ksure.or.kr", captured[0]["referer"])
        self.assertTrue(all(item["timeout"] == 30 for item in captured))
        self.assertEqual(_payload(), payload)
        self.assertNotIn("api/rsrch", repr(adapter))

    def test_transport_size_and_contract_errors_are_safe(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            KsureCountryPolicyAdapter(endpoint="http://example.test/policy")

        def unauthorized(request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "unauthorized", {}, None
            )

        with self.assertRaisesRegex(KsureCountryPolicyError, "HTTP 401"):
            KsureCountryPolicyAdapter(opener=unauthorized).fetch()
        with self.assertRaisesRegex(KsureCountryPolicyError, "size limit"):
            KsureCountryPolicyAdapter(
                max_bytes=4,
                opener=lambda request, timeout: _Response(b"12345"),
            ).fetch()
        with self.assertRaisesRegex(KsureCountryPolicyError, "getNationLst"):
            KsureCountryPolicyAdapter(
                opener=lambda request, timeout: _Response(b"{}")
            ).fetch()

    def test_collect_preserves_raw_catalog(self) -> None:
        adapter = KsureCountryPolicyAdapter(
            opener=lambda request, timeout: _response_for(request)
        )
        observed = datetime(2026, 7, 27, 2, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.collect(Path(tmp), retrieved_at=observed)
            ref, stored = read_snapshot(path)

        self.assertEqual("KSURE_COUNTRY_POLICY_API", ref.source_id)
        self.assertEqual(observed, ref.observed_at)
        self.assertEqual(_payload(), stored)


class KsureCountryPolicyBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        observed = datetime(2026, 7, 27, 2, tzinfo=UTC)
        self.dataset = SnapshotDataset(
            SnapshotRef(
                "KSURE_COUNTRY_POLICY_API",
                "20260727T020000Z",
                observed,
                observed,
                "sha256:test",
            ),
            parse_ksure_country_policy_payload(_payload()),
        )
        self.case = TradeCase(
            "EXP-1",
            TradeDirection.EXPORT,
            "USD",
            1000,
            date(2026, 8, 31),
            PaymentMethod.TT,
            counterparty_country="SY",
        )

    def test_snapshot_policy_becomes_attested_profile_fact(self) -> None:
        profile, evidence = bind_country_policy(
            KsureCaseProfile(), self.dataset, self.case
        )

        self.assertTrue(profile.country_restricted)
        assertion = profile.assertions()[0]
        self.assertEqual("counterparty.country_restricted", assertion.field)
        self.assertEqual((evidence.evidence_id,), assertion.evidence_ids)
        self.assertEqual(("KSURE_COUNTRY_POLICY_API",), evidence.source_ids)
        self.assertTrue(
            evidence.payload["facts"]["counterparty.country_restricted"]
        )
        self.assertEqual("restricted", evidence.payload["policy_status"])
        self.assertEqual("sha256:test", evidence.payload["snapshot"]["content_hash"])

    def test_missing_unknown_or_preconfigured_country_is_not_guessed(self) -> None:
        no_country = TradeCase(
            "EXP-2",
            TradeDirection.EXPORT,
            "USD",
            1000,
            date(2026, 8, 31),
            PaymentMethod.TT,
        )
        unknown = TradeCase(
            "EXP-3",
            TradeDirection.EXPORT,
            "USD",
            1000,
            date(2026, 8, 31),
            PaymentMethod.TT,
            counterparty_country="ZZ",
        )
        unknown_status = TradeCase(
            "EXP-4",
            TradeDirection.EXPORT,
            "USD",
            1000,
            date(2026, 8, 31),
            PaymentMethod.TT,
            counterparty_country="MF",
        )
        for case in (no_country, unknown, unknown_status):
            with self.subTest(case=case.case_id):
                with self.assertRaises(FactContractError):
                    bind_country_policy(KsureCaseProfile(), self.dataset, case)
        with self.assertRaisesRegex(FactContractError, "cannot be overridden"):
            bind_country_policy(
                KsureCaseProfile(country_restricted=False),
                self.dataset,
                self.case,
            )


if __name__ == "__main__":
    unittest.main()
