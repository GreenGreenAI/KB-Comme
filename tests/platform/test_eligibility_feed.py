import json
import os
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tradeflow.domain.dataset_registry import (
    DatasetRegistry,
    default_parser_registry,
)
from tradeflow.domain.datasets import (
    DatasetContractError,
    EligibilityEvidenceDataset,
    StaleDatasetError,
    parse_eligibility_evidence_payload,
)
from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.integration.eligibility_feed import (
    EligibilityFeedError,
    JsonEligibilityEvidenceAdapter,
)
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot
from tradeflow.knowledge.eligibility_evidence import EligibilityEvidenceAssembler
from tradeflow.knowledge.facts import FactCatalog
from tradeflow.runtime.eligibility_provider import (
    SnapshotEligibilityEvidenceProvider,
)


ROOT = Path(__file__).resolve().parents[2]
OBSERVED = datetime(2026, 7, 27, tzinfo=UTC)


def payload() -> dict:
    return {
        "schema_version": "1.0",
        "version": "company-20260727-v1",
        "observed_at": OBSERVED.isoformat(),
        "provider_key": "company_qualification",
        "records": [
            {
                "evidence_id": "company:C1:20260727",
                "company_id": "C1",
                "subject_kind": "company",
                "subject_id": "C1",
                "valid_until": "2026-08-27T00:00:00+00:00",
                "facts": {
                    "company.is_sme": True,
                    "company.size": "small",
                    "company.credit_issue_free": True,
                },
            },
            {
                "evidence_id": "importer:C1:EXP-1:20260727",
                "company_id": "C1",
                "subject_kind": "case",
                "subject_id": "EXP-1",
                "valid_until": "2026-08-27T00:00:00+00:00",
                "facts": {"counterparty.ksure_importer_grade": "B"},
            },
            {
                "evidence_id": "collision:C2:EXP-1:20260727",
                "company_id": "C2",
                "subject_kind": "case",
                "subject_id": "EXP-1",
                "valid_until": "2026-08-27T00:00:00+00:00",
                "facts": {"counterparty.ksure_importer_grade": "G"},
            },
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


class EligibilityPayloadTests(unittest.TestCase):
    def test_payload_is_normalized_without_losing_scope_or_validity(self) -> None:
        dataset = parse_eligibility_evidence_payload(payload())

        self.assertIsInstance(dataset, EligibilityEvidenceDataset)
        self.assertEqual("company_qualification", dataset.provider_key)
        self.assertEqual("C1", dataset.records[1].company_id)
        self.assertEqual("case", dataset.records[1].subject_kind.value)
        self.assertEqual(
            datetime(2026, 8, 27, tzinfo=UTC),
            dataset.records[1].valid_until,
        )
        with self.assertRaises(TypeError):
            dataset.records[0].facts["company.size"] = "large"

    def test_ambiguous_or_unbounded_payload_shapes_fail_closed(self) -> None:
        cases = []
        duplicate = payload()
        duplicate["records"].append(dict(duplicate["records"][0]))
        cases.append((duplicate, "duplicate evidence_id"))
        wrong_owner = payload()
        wrong_owner["records"][0]["company_id"] = "C2"
        cases.append((wrong_owner, "subject_id must equal company_id"))
        nested = payload()
        nested["records"][0]["facts"]["company.size"] = {"value": "small"}
        cases.append((nested, "non-null JSON scalar"))
        null_fact = payload()
        null_fact["records"][0]["facts"]["company.size"] = None
        cases.append((null_fact, "non-null JSON scalar"))
        naive = payload()
        naive["records"][0]["valid_until"] = "2026-08-27T00:00:00"
        cases.append((naive, "time zone"))
        expired_before_observation = payload()
        expired_before_observation["records"][0]["valid_until"] = (
            "2026-07-26T00:00:00+00:00"
        )
        cases.append((expired_before_observation, "precedes observed_at"))
        leaked_root_secret = payload()
        leaked_root_secret["access_token"] = "must-not-be-stored"
        cases.append((leaked_root_secret, "unknown fields: access_token"))
        leaked_record_secret = payload()
        leaked_record_secret["records"][0]["raw_credential"] = "must-not-be-stored"
        cases.append((leaked_record_secret, "unknown fields: raw_credential"))

        for document, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(DatasetContractError, message):
                    parse_eligibility_evidence_payload(document)


class EligibilityFeedAdapterTests(unittest.TestCase):
    def test_https_and_non_secret_repr_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            JsonEligibilityEvidenceAdapter(
                endpoint="http://connector.example/evidence",
                source_id="COMPANY_QUALIFICATION_FEED",
                adapter_key="company_qualification_json",
            )
        adapter = JsonEligibilityEvidenceAdapter(
            endpoint="https://connector.example/evidence?tenant=secret",
            source_id="COMPANY_QUALIFICATION_FEED",
            adapter_key="company_qualification_json",
            bearer_token="header-secret",
        )
        self.assertNotIn("secret", repr(adapter))

    def test_environment_credential_is_sent_but_never_stored_in_snapshot(self) -> None:
        captured = {}

        def opener(request, *, timeout):
            captured["authorization"] = request.get_header("Authorization")
            return Response(json.dumps(payload()).encode("utf-8"))

        adapter = JsonEligibilityEvidenceAdapter(
            endpoint="https://connector.example/evidence",
            source_id="COMPANY_QUALIFICATION_FEED",
            adapter_key="company_qualification_json",
            bearer_token_env="TRADEFLOW_TEST_ELIGIBILITY_TOKEN",
            opener=opener,
        )
        with patch.dict(
            os.environ,
            {"TRADEFLOW_TEST_ELIGIBILITY_TOKEN": "very-secret"},
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = adapter.collect(
                    tmp,
                    retrieved_at=OBSERVED + timedelta(hours=1),
                )
                _, stored = read_snapshot(path)

        self.assertEqual("Bearer very-secret", captured["authorization"])
        self.assertEqual(payload(), stored)
        self.assertNotIn("very-secret", json.dumps(stored))

    def test_safe_errors_size_limit_and_future_observation(self) -> None:
        def http_error(request, *, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "unauthorized", {}, None
            )

        adapter = JsonEligibilityEvidenceAdapter(
            endpoint="https://connector.example/evidence?token=query-secret",
            source_id="COMPANY_QUALIFICATION_FEED",
            adapter_key="company_qualification_json",
            bearer_token="header-secret",
            opener=http_error,
        )
        with self.assertRaises(EligibilityFeedError) as caught:
            adapter.fetch()
        self.assertEqual("eligibility feed returned HTTP 401", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

        oversized = JsonEligibilityEvidenceAdapter(
            endpoint="https://connector.example/evidence",
            source_id="COMPANY_QUALIFICATION_FEED",
            adapter_key="company_qualification_json",
            max_bytes=4,
            opener=lambda request, timeout: Response(b"12345"),
        )
        with self.assertRaisesRegex(EligibilityFeedError, "size limit"):
            oversized.fetch()

        future = JsonEligibilityEvidenceAdapter(
            endpoint="https://connector.example/evidence",
            source_id="COMPANY_QUALIFICATION_FEED",
            adapter_key="company_qualification_json",
            opener=lambda request, timeout: Response(
                json.dumps(payload()).encode("utf-8")
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(EligibilityFeedError, "later than"):
                future.collect(tmp, retrieved_at=OBSERVED - timedelta(seconds=1))


class SnapshotEligibilityProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = DatasetRegistry.from_json(
            ROOT / "data" / "dataset_registry.json"
        )
        self.program = TradeProgram(
            "P1",
            CompanyProfile("C1", "Exporter", country_code="KR"),
            (
                TradeCase(
                    "EXP-1",
                    TradeDirection.EXPORT,
                    "USD",
                    Decimal("1000"),
                    date(2026, 9, 1),
                    PaymentMethod.TT,
                ),
            ),
            as_of=date(2026, 7, 27),
        )

    def test_private_registry_snapshot_becomes_tenant_safe_fact_input(self) -> None:
        definition = self.registry.get("COMPANY_QUALIFICATION_EVIDENCE_V1")
        adapter = JsonEligibilityEvidenceAdapter(
            endpoint="https://connector.example/evidence",
            source_id=definition.source_id,
            adapter_key=definition.adapter_key,
            opener=lambda request, timeout: Response(
                json.dumps(payload()).encode("utf-8")
            ),
        )
        at = OBSERVED + timedelta(hours=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.collect(tmp, retrieved_at=at)
            dataset = self.registry.read_snapshot(
                definition.dataset_id,
                path,
                parsers=default_parser_registry(),
                evaluated_at=at,
            )

        provider = SnapshotEligibilityEvidenceProvider(
            dataset,
            definition=definition,
        )
        records = provider.collect(program=self.program, evaluated_at=at)

        self.assertEqual(2, len(records))
        self.assertEqual(
            {"company:C1:20260727", "importer:C1:EXP-1:20260727"},
            {record.metadata.evidence_id for record in records},
        )
        self.assertTrue(
            all(record.metadata.content_hash == dataset.ref.content_hash for record in records)
        )
        fact_input = EligibilityEvidenceAssembler(
            FactCatalog.from_json(ROOT / "knowledge" / "fact_catalog.json"),
            trusted_source_ids={definition.source_id},
        ).assemble(
            program=self.program,
            records=records,
            evaluated_at=at,
            required_fields_by_case={
                "EXP-1": (
                    "company.size",
                    "counterparty.ksure_importer_grade",
                )
            },
        )
        assertions = {
            item.field: item.value
            for item in fact_input.assertions_by_case["EXP-1"]
        }
        self.assertEqual("small", assertions["company.size"])
        self.assertEqual("B", assertions["counterparty.ksure_importer_grade"])
        self.assertEqual((), fact_input.missing_fields_by_case["EXP-1"])

        with self.assertRaisesRegex(StaleDatasetError, "stale"):
            provider.collect(
                program=self.program,
                evaluated_at=at + timedelta(days=2),
            )
        with self.assertRaisesRegex(TypeError, "definition is not"):
            SnapshotEligibilityEvidenceProvider(
                dataset,
                definition=self.registry.get("ERP_TRADE_FEED_V1"),
            )
        with self.assertRaisesRegex(ValueError, "source_id does not match"):
            SnapshotEligibilityEvidenceProvider(
                dataset,
                definition=replace(definition, source_id="OTHER_SOURCE"),
            )
        with self.assertRaisesRegex(ValueError, "provider_key does not match"):
            SnapshotEligibilityEvidenceProvider(
                replace(
                    dataset,
                    value=replace(dataset.value, provider_key="ksure_credit"),
                ),
                definition=definition,
            )

    def test_registry_cross_checks_payload_and_envelope_identity(self) -> None:
        definition = self.registry.get("COMPANY_QUALIFICATION_EVIDENCE_V1")
        at = OBSERVED + timedelta(hours=1)
        cases = (
            (
                "different-version",
                OBSERVED,
                "evidence version",
            ),
            (
                payload()["version"],
                OBSERVED + timedelta(seconds=1),
                "observed_at does not match",
            ),
        )
        for version, observed_at, message in cases:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as tmp:
                    path = write_snapshot(
                        tmp,
                        build_envelope(
                            source_id=definition.source_id,
                            version=version,
                            observed_at=observed_at,
                            retrieved_at=at,
                            payload=payload(),
                        ),
                    )
                    with self.assertRaisesRegex(DatasetContractError, message):
                        self.registry.read_snapshot(
                            definition.dataset_id,
                            path,
                            parsers=default_parser_registry(),
                            evaluated_at=at,
                        )


if __name__ == "__main__":
    unittest.main()
