"""Worker isolation and routing (§4.2[2], §9.3).

The rule the tests below defend is that a failure narrows the answer without
destroying it, and without being papered over: whatever a worker could not
produce is reported as missing rather than guessed.
"""

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.response import build_response
from tradeflow.domain.enums import (
    AvailabilityStatus,
    FinancialInstrumentKind,
    HedgeMeasureCategory,
)
from tradeflow.domain.models import HedgeMeasure
from tradeflow.domain.snapshot_file import content_hash

KST = timezone(timedelta(hours=9))
AS_OF = date(2026, 7, 26)
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=KST)

CASES = [
    {"direction": "수입", "amount": "60000", "expected_payment_date": "2026-08-25"},
    {"direction": "수출", "amount": "100000", "expected_payment_date": "2026-10-24"},
]


def _program(**profile):
    """A program with no company profile and no declared trade structure.

    That is the ordinary starting point, and §4.2[2] routes the support and
    compliance workers out of the plan until one of them is supplied.
    """
    return intake(
        CASES, opening_balances={"USD": "20000"}, as_of=AS_OF, **profile
    ).program


def _available_measure() -> HedgeMeasure:
    return HedgeMeasure(
        "TEST_KSURE_FX",
        HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
        FinancialInstrumentKind.KSURE_FX_INSURANCE,
        AvailabilityStatus.AVAILABLE,
        contract_rate=Decimal("1400"),
        cost_rate=Decimal("0.004"),
        source_ids=("TEST_VERIFIED_PRICING",),
    )


def _snapshot_root(directory: Path, *, observed: str = "2026-07-24") -> Path:
    """A small but real ECOS-shaped snapshot, enough for a 60-day window."""
    import json

    start = date(2026, 1, 5)
    rows = [
        {
            "TIME": (start + timedelta(days=i)).strftime("%Y%m%d"),
            "DATA_VALUE": f"{1400 + (i % 7) * 3}",
        }
        for i in range(140)
    ]
    rows[-1]["TIME"] = observed.replace("-", "")
    payload = {"list_total_count": len(rows), "row": rows}
    root = directory / "snapshots"
    (root / "ECOS_USD_KRW").mkdir(parents=True)
    (root / "ECOS_USD_KRW" / f"{observed}.json").write_text(
        json.dumps(
            {
                "source_id": "ECOS_USD_KRW",
                "version": observed,
                "observed_at": f"{observed}T00:00:00+09:00",
                "retrieved_at": f"{observed}T09:00:00+09:00",
                "content_hash": content_hash(payload),
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    return root


class WorkerIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_missing_snapshot_does_not_take_the_answer_down(self) -> None:
        """The exposure figures survive an unavailable market worker (§9.3)."""
        analysis = analyze(
            _program(), snapshot_root=self.root / "absent", as_of=NOW
        )

        self.assertIn("exposure", analysis.report.completed)
        self.assertIn("market_scenario", analysis.report.failed)
        self.assertIsNone(analysis.band)
        self.assertEqual(
            Decimal("40000"), analysis.cashflow["funding_gap"][0]["peak_amount"]
        )
        self.assertEqual(
            "40000",
            build_response(analysis)["cashflow_analysis"]["funding_gap"][0][
                "peak_amount"
            ],
        )

    def test_a_failed_worker_is_reported_not_hidden(self) -> None:
        analysis = analyze(
            _program(), snapshot_root=self.root / "absent", as_of=NOW
        )
        response = build_response(analysis)

        self.assertTrue(response["review_required"])
        self.assertTrue(
            any("market_scenario" in item for item in response["missing_information"])
        )
        self.assertIsNone(response["market_scenario"])

    def test_hedge_is_skipped_with_a_reason_when_its_input_is_absent(self) -> None:
        analysis = analyze(
            _program(), snapshot_root=self.root / "absent", as_of=NOW
        )

        self.assertIn("hedge", analysis.report.skipped)
        self.assertIn("환율", analysis.report.skipped["hedge"])

    def test_stale_snapshot_stops_the_market_worker(self) -> None:
        root = _snapshot_root(self.root)
        much_later = datetime(2026, 9, 1, tzinfo=KST)

        analysis = analyze(_program(), snapshot_root=root, as_of=much_later)

        self.assertIsNone(analysis.band)
        self.assertIn("market_scenario", analysis.report.failed)


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = _snapshot_root(Path(self._tmp.name))

    def test_every_planned_worker_runs_on_a_complete_program(self) -> None:
        analysis = analyze(
            _program(is_sme=True),
            snapshot_root=self.root,
            baseline_profit=Decimal("6000000"),
            profit_floor=Decimal("4000000"),
            hedge_measures=(_available_measure(),),
            as_of=NOW,
        )

        self.assertIn("exposure", analysis.report.completed)
        self.assertIn("support", analysis.report.completed)
        self.assertIn("market_scenario", analysis.report.completed)
        self.assertIn("hedge", analysis.report.completed)

    def test_compliance_is_not_called_on_an_undeclared_structure(self) -> None:
        """§4.2[2] routes it in only when the trade structure calls for it.

        Its nineteen rules are each about netting, third-party payment, a
        mutual account or an over-long period. Running them on a plain T/T
        trade returned nineteen INSUFFICIENT_INFORMATION — the same absence of
        information as one sentence, spread until nobody reads it.
        """
        analysis = analyze(_program(), snapshot_root=self.root, as_of=NOW)

        self.assertNotIn("compliance", analysis.report.completed)
        self.assertFalse(analysis.plan.runs("compliance"))

    def test_not_calling_compliance_never_reads_as_a_clearance(self) -> None:
        """The one conclusion this product must not imply by omission."""
        analysis = analyze(_program(), snapshot_root=self.root, as_of=NOW)
        reason = analysis.report.skipped["compliance"]

        self.assertIn("알려주세요", reason)
        self.assertIn("신고 불필요로 판단하지 않습니다", reason)
        self.assertTrue(
            any("compliance" in item for item in analysis.report.missing_information())
        )

    def test_a_period_the_dates_imply_puts_compliance_back_in(self) -> None:
        """§5.5's period tests follow from dates intake already collected."""
        program = intake(
            [
                {
                    "direction": "수출",
                    "amount": "150000",
                    "expected_payment_date": "2026-08-25",
                    "expected_shipment_date": "2028-03-01",
                }
            ],
            as_of=AS_OF,
        ).program

        analysis = analyze(program, snapshot_root=self.root, as_of=NOW)

        self.assertIn("compliance", analysis.report.completed)
        matched = [
            item
            for item in analysis.decision_packet.decisions
            if "days_before_shipment" in " ".join(item.reasons)
        ]
        self.assertTrue(matched, "derived day count did not reach the rules")

    def test_hedge_needs_a_baseline_profit_and_says_so(self) -> None:
        analysis = analyze(
            _program(),
            snapshot_root=self.root,
            hedge_measures=(_available_measure(),),
            as_of=NOW,
        )

        self.assertIsNone(analysis.hedge)
        self.assertIn("영업이익", analysis.report.skipped["hedge"])

    def test_profit_floor_must_be_explicit(self) -> None:
        analysis = analyze(
            _program(),
            snapshot_root=self.root,
            baseline_profit=Decimal("6000000"),
            hedge_measures=(_available_measure(),),
            as_of=NOW,
        )

        self.assertIsNone(analysis.hedge)
        self.assertEqual(("profit_floor",), analysis.required_inputs)
        self.assertIn("손익 하한", analysis.report.skipped["hedge"])

    def test_a_company_profile_puts_the_support_worker_in_the_plan(self) -> None:
        analysis = analyze(
            _program(is_sme=True), snapshot_root=self.root, as_of=NOW
        )

        self.assertIn("support", analysis.report.completed)
        self.assertIsNotNone(analysis.decision_packet)
        self.assertTrue(analysis.review_required)

    def test_without_a_profile_the_support_worker_states_what_it_needs(self) -> None:
        analysis = analyze(_program(), snapshot_root=self.root, as_of=NOW)

        self.assertNotIn("support", analysis.report.completed)
        self.assertIn("기업규모", analysis.report.skipped["support"])

    def test_hedge_is_not_fabricated_without_verified_availability(self) -> None:
        analysis = analyze(
            _program(is_sme=True),
            snapshot_root=self.root,
            baseline_profit=Decimal("6000000"),
            profit_floor=Decimal("4000000"),
            as_of=NOW,
        )

        self.assertIsNone(analysis.hedge)
        self.assertIn("검증된 이용 가능", analysis.report.skipped["hedge"])

    def test_response_reports_the_snapshot_it_used(self) -> None:
        analysis = analyze(
            _program(is_sme=True), snapshot_root=self.root, as_of=NOW
        )
        response = build_response(analysis)

        self.assertEqual(
            "2026-07-24", response["calculation_versions"]["snapshot_version"]
        )
        self.assertTrue(
            any(item["role"] == "market_data" for item in response["evidence"])
        )
        self.assertEqual(analysis.decision_packet.packet_id, response["packet_id"])
        self.assertEqual(
            str(analysis.adverse_cashflow_amount),
            response["market_scenario"]["adverse_cashflow_amount"],
        )

    def test_summary_is_left_for_synthesis_to_write(self) -> None:
        response = build_response(
            analyze(_program(), snapshot_root=self.root, as_of=NOW)
        )

        self.assertEqual("", response["summary"])


if __name__ == "__main__":
    unittest.main()
