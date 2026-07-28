import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tradeflow.domain.dataset_registry import (
    DatasetRegistry,
    default_parser_registry,
)
from tradeflow.domain.models import CompanyProfile
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.analysis_service import (
    AnalysisErrorCode,
    AnalysisService,
    AnalysisServiceError,
    CaseAnalysisInputs,
    SnapshotAnalysisRequest,
    decision_packet_document,
    snapshot_analysis_request_from_document,
)
from tradeflow.runtime.pipeline import TradeFlowPipeline

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))


def _trade_payload(version: str, observed_at: datetime) -> dict:
    return {
        "schema_version": "1.0",
        "version": version,
        "observed_at": observed_at.isoformat(),
        "opening_balances": {"USD": "100"},
        "trades": [
            {
                "case_id": "T-1",
                "direction": "export",
                "currency": "USD",
                "amount": "1000.25",
                "expected_payment_date": "2026-08-31",
                "payment_method": "tt",
                "counterparty_country": "US",
            }
        ],
    }


def _bizinfo_payload() -> dict:
    return {
        "jsonArray": {
            "item": [
                {
                    "pblancId": "B-1",
                    "pblancNm": "지원 공고",
                    "jrsdInsttNm": "기관",
                    "pldirSportRealmLclasCodeNm": "수출",
                    "trgetNm": "중소기업",
                    "pblancUrl": "https://www.bizinfo.go.kr/example",
                    "totCnt": "1",
                }
            ]
        }
    }


class AnalysisRequestTests(unittest.TestCase):
    def test_json_request_parser_preserves_decimal_and_rejects_ambiguous_input(self) -> None:
        document = {
            "schema_version": "1.0",
            "dataset_id": "ERP_TRADE_FEED_V1",
            "snapshot_version": "erp-v1",
            "program_id": "P-1",
            "as_of": "2026-07-27",
            "company": {
                "company_id": "C-1",
                "name": "Exporter",
                "is_sme": True,
                "annual_export_usd": "1000000.25",
            },
        }

        request = snapshot_analysis_request_from_document(document)

        self.assertEqual("1000000.25", str(request.company.annual_export_usd))
        self.assertEqual(date(2026, 7, 27), request.as_of)

        document["company"]["annual_export_usd"] = 1000000.25
        with self.assertRaises(AnalysisServiceError) as caught:
            snapshot_analysis_request_from_document(document)
        self.assertEqual(AnalysisErrorCode.INVALID_REQUEST, caught.exception.code)

        document["company"]["annual_export_usd"] = "100"
        document["unexpected"] = True
        with self.assertRaisesRegex(AnalysisServiceError, "unknown request fields"):
            snapshot_analysis_request_from_document(document)

    def test_identifiers_cannot_select_an_arbitrary_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "snapshot_version"):
            SnapshotAnalysisRequest(
                dataset_id="ERP_TRADE_FEED_V1",
                snapshot_version="../secret",
                program_id="P-1",
                company=CompanyProfile("C-1", "Exporter"),
                as_of=date(2026, 7, 27),
            )

    def test_case_input_mappings_are_copied_and_read_only(self) -> None:
        source = {"T-1": ()}
        inputs = CaseAnalysisInputs(source)
        source["T-2"] = ()

        self.assertEqual(("T-1",), tuple(inputs.assertions_by_case))
        with self.assertRaises(TypeError):
            inputs.assertions_by_case["T-2"] = ()


class AnalysisServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project_root = Path(self.tmp.name)
        self.datasets = DatasetRegistry.from_json(
            ROOT / "data" / "dataset_registry.json"
        )
        knowledge = KnowledgeRepository.from_json(
            ROOT / "knowledge" / "source_registry.json",
            ROOT / "knowledge" / "rulepacks" / "demo_trade_support.json",
        )
        self.service = AnalysisService(
            project_root=self.project_root,
            datasets=self.datasets,
            parsers=default_parser_registry(),
            pipeline=TradeFlowPipeline(knowledge),
        )
        self.at = datetime(2026, 7, 27, 9, tzinfo=KST)
        self.request = SnapshotAnalysisRequest(
            dataset_id="ERP_TRADE_FEED_V1",
            snapshot_version="erp-v1",
            program_id="P-1",
            company=CompanyProfile("C-1", "Exporter", is_sme=True),
            as_of=date(2026, 7, 27),
        )

    def write_trade(self, observed_at: datetime | None = None) -> Path:
        observed = observed_at or self.at
        payload = _trade_payload("erp-v1", observed)
        definition = self.datasets.get("ERP_TRADE_FEED_V1")
        return write_snapshot(
            self.project_root / definition.storage_root,
            build_envelope(
                source_id=definition.source_id,
                version="erp-v1",
                observed_at=observed,
                retrieved_at=observed,
                payload=payload,
            ),
        )

    def assert_error(
        self,
        code: AnalysisErrorCode,
        request: SnapshotAnalysisRequest,
        *,
        evaluated_at: datetime | None = None,
        case_inputs: CaseAnalysisInputs | None = None,
    ) -> AnalysisServiceError:
        with self.assertRaises(AnalysisServiceError) as caught:
            self.service.analyze(
                request,
                evaluated_at=evaluated_at or self.at,
                case_inputs=case_inputs,
            )
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_verified_snapshot_produces_reproducible_api_document(self) -> None:
        self.write_trade()

        first = self.service.analyze(self.request, evaluated_at=self.at)
        second = self.service.analyze(self.request, evaluated_at=self.at)
        document = decision_packet_document(first)
        encoded = json.dumps(document, ensure_ascii=False, sort_keys=True)

        self.assertEqual(first.packet_id, second.packet_id)
        self.assertEqual("1.6", document["schema_version"])
        self.assertEqual("100", document["exposures"][0]["opening_balance"])
        self.assertEqual("1000.25", document["exposures"][0]["total_inflow"])
        self.assertEqual(1, len(document["decisions"]))
        self.assertEqual({}, document["decisions"][0]["candidate_outcome"])
        self.assertEqual(
            "expert_confirmation_required",
            document["decisions"][0]["status"],
        )
        self.assertEqual([], document["actions"])
        self.assertIn("ERP_TRADE_FEED", encoded)
        self.assertNotIn("1000.25e", encoded.lower())

    def test_unknown_missing_stale_and_wrong_kind_have_stable_error_codes(self) -> None:
        unknown = SnapshotAnalysisRequest(
            "UNKNOWN_DATASET",
            "v1",
            "P-1",
            CompanyProfile("C-1", "Exporter"),
            date(2026, 7, 27),
        )
        self.assert_error(AnalysisErrorCode.UNKNOWN_DATASET, unknown)
        self.assert_error(AnalysisErrorCode.SNAPSHOT_NOT_FOUND, self.request)

        self.write_trade(self.at - timedelta(days=2))
        self.assert_error(
            AnalysisErrorCode.SNAPSHOT_STALE,
            self.request,
            evaluated_at=self.at,
        )

        biz_definition = self.datasets.get("BIZINFO_SUPPORT_PROGRAMS_DAILY")
        write_snapshot(
            self.project_root / biz_definition.storage_root,
            build_envelope(
                source_id=biz_definition.source_id,
                version="biz-v1",
                observed_at=self.at,
                retrieved_at=self.at,
                payload=_bizinfo_payload(),
            ),
        )
        wrong_kind = SnapshotAnalysisRequest(
            "BIZINFO_SUPPORT_PROGRAMS_DAILY",
            "biz-v1",
            "P-1",
            CompanyProfile("C-1", "Exporter"),
            date(2026, 7, 27),
        )
        self.assert_error(AnalysisErrorCode.WRONG_DATASET_KIND, wrong_kind)

    def test_corrupted_snapshot_and_case_configuration_fail_closed(self) -> None:
        path = self.write_trade()
        document = json.loads(path.read_text(encoding="utf-8"))
        document["payload"]["opening_balances"]["USD"] = "999999"
        path.write_text(json.dumps(document), encoding="utf-8")

        error = self.assert_error(AnalysisErrorCode.SNAPSHOT_INVALID, self.request)
        self.assertNotIn(str(path), str(error))

        path.unlink()
        self.write_trade()
        self.assert_error(
            AnalysisErrorCode.INVALID_CASE_INPUT,
            self.request,
            case_inputs=CaseAnalysisInputs({}),
        )

    def test_analysis_rejects_future_as_of_and_future_snapshot_leakage(self) -> None:
        self.write_trade()
        future_request = SnapshotAnalysisRequest(
            dataset_id=self.request.dataset_id,
            snapshot_version=self.request.snapshot_version,
            program_id=self.request.program_id,
            company=self.request.company,
            as_of=date(2026, 7, 28),
        )
        self.assert_error(AnalysisErrorCode.INVALID_REQUEST, future_request)

        historical_request = SnapshotAnalysisRequest(
            dataset_id=self.request.dataset_id,
            snapshot_version=self.request.snapshot_version,
            program_id=self.request.program_id,
            company=self.request.company,
            as_of=date(2026, 7, 26),
        )
        self.assert_error(AnalysisErrorCode.SNAPSHOT_INVALID, historical_request)


if __name__ == "__main__":
    unittest.main()
