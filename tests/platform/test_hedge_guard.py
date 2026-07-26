"""Boundary invariants for hedge measure availability.

These tests cover the guard only. They construct measures with a status already
decided, so they say nothing about whether collateral facts produce the right
status: that judgement is the knowledge layer's and is tested with its rules.
"""

import unittest
from decimal import Decimal

from tradeflow.domain.enums import (
    AvailabilityStatus,
    FinancialInstrumentKind,
    HedgeMeasureCategory,
    HedgeStrategyKind,
)
from tradeflow.domain.models import HedgeMeasure
from tradeflow.tools.hedge import (
    UnusableMeasureError,
    assert_all_usable,
    review_measures,
    unavailable_measures,
    usable_measures,
)


BLOCKED_FORWARD = HedgeMeasure(
    "BANK_FORWARD",
    HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
    FinancialInstrumentKind.FORWARD,
    AvailabilityStatus.UNAVAILABLE,
    status_reasons=("담보 또는 신용라인 미보유",),
)
KSURE = HedgeMeasure(
    "KSURE_FX",
    HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
    FinancialInstrumentKind.KSURE_FX_INSURANCE,
    AvailabilityStatus.AVAILABLE,
    contract_rate=Decimal("1380.00"),
    cost_rate=Decimal("0.004"),
    source_ids=("KSURE_FX_GUIDE",),
)
UNDETERMINED_NATURAL = HedgeMeasure(
    "NATURAL_OFFSET",
    HedgeMeasureCategory.STRATEGY,
    HedgeStrategyKind.NATURAL,
    AvailabilityStatus.INSUFFICIENT_INFORMATION,
    status_reasons=("반대방향 현금흐름의 결제일 미확인",),
)


class HedgeMeasureInvariantTests(unittest.TestCase):
    def test_non_available_status_must_state_a_reason(self) -> None:
        for status in (
            AvailabilityStatus.UNAVAILABLE,
            AvailabilityStatus.CONDITIONAL,
            AvailabilityStatus.INSUFFICIENT_INFORMATION,
            AvailabilityStatus.EXPERT_CONFIRMATION_REQUIRED,
        ):
            with self.subTest(status=status), self.assertRaises(ValueError):
                HedgeMeasure(
                    "BANK_FORWARD",
                    HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
                    FinancialInstrumentKind.FORWARD,
                    status,
                )

    def test_available_measure_must_not_carry_reasons(self) -> None:
        with self.assertRaises(ValueError):
            HedgeMeasure(
                "BANK_FORWARD",
                HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
                FinancialInstrumentKind.FORWARD,
                AvailabilityStatus.AVAILABLE,
                status_reasons=("담보 미보유",),
            )

    def test_category_and_kind_must_agree(self) -> None:
        with self.assertRaises(ValueError):
            HedgeMeasure(
                "NATURAL_OFFSET",
                HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
                HedgeStrategyKind.NATURAL,
                AvailabilityStatus.AVAILABLE,
            )

    def test_strategy_must_not_be_priced(self) -> None:
        with self.assertRaises(ValueError):
            HedgeMeasure(
                "NATURAL_OFFSET",
                HedgeMeasureCategory.STRATEGY,
                HedgeStrategyKind.NATURAL,
                AvailabilityStatus.AVAILABLE,
                contract_rate=Decimal("1380.00"),
            )

    def test_negative_cost_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HedgeMeasure(
                "KSURE_FX",
                HedgeMeasureCategory.FINANCIAL_INSTRUMENT,
                FinancialInstrumentKind.KSURE_FX_INSURANCE,
                AvailabilityStatus.AVAILABLE,
                cost_rate=Decimal("-0.001"),
            )


class HedgeGuardTests(unittest.TestCase):
    def test_only_available_measures_are_usable(self) -> None:
        candidates = (BLOCKED_FORWARD, KSURE, UNDETERMINED_NATURAL)

        self.assertEqual((KSURE,), usable_measures(candidates))

    def test_undetermined_measure_is_not_treated_as_ruled_out(self) -> None:
        candidates = (BLOCKED_FORWARD, KSURE, UNDETERMINED_NATURAL)

        self.assertEqual((BLOCKED_FORWARD,), unavailable_measures(candidates))
        self.assertEqual((UNDETERMINED_NATURAL,), review_measures(candidates))

    def test_status_reasons_survive_for_the_response(self) -> None:
        blocked = unavailable_measures((BLOCKED_FORWARD, KSURE))

        self.assertEqual(("담보 또는 신용라인 미보유",), blocked[0].status_reasons)

    def test_optimizer_boundary_rejects_measure_that_is_not_available(self) -> None:
        with self.assertRaises(UnusableMeasureError) as caught:
            assert_all_usable((KSURE, BLOCKED_FORWARD))

        self.assertIn("BANK_FORWARD", str(caught.exception))
        self.assertIn("담보 또는 신용라인 미보유", str(caught.exception))

    def test_optimizer_boundary_rejects_undetermined_measure(self) -> None:
        with self.assertRaises(UnusableMeasureError):
            assert_all_usable((KSURE, UNDETERMINED_NATURAL))

    def test_filtered_candidates_pass_the_boundary(self) -> None:
        candidates = (BLOCKED_FORWARD, KSURE, UNDETERMINED_NATURAL)

        assert_all_usable(usable_measures(candidates))


if __name__ == "__main__":
    unittest.main()
