import unittest
from decimal import Decimal

from tradeflow.domain.enums import InstrumentKind
from tradeflow.domain.models import HedgeInstrument
from tradeflow.tools.hedge import (
    UnavailableInstrumentError,
    assert_all_available,
    excluded_instruments,
    usable_instruments,
)


FORWARD_WITHOUT_COLLATERAL = HedgeInstrument(
    "BANK_FORWARD",
    InstrumentKind.FORWARD,
    available=False,
    exclusion_reasons=("담보 또는 신용라인 미보유",),
)
KSURE = HedgeInstrument(
    "KSURE_FX",
    InstrumentKind.KSURE_FX_INSURANCE,
    available=True,
    contract_rate=Decimal("1380.00"),
    cost_rate=Decimal("0.004"),
    source_ids=("KSURE_FX_GUIDE",),
)


class HedgeInstrumentInvariantTests(unittest.TestCase):
    def test_unavailable_instrument_must_state_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            HedgeInstrument("BANK_FORWARD", InstrumentKind.FORWARD, available=False)

    def test_available_instrument_must_not_carry_exclusion_reasons(self) -> None:
        with self.assertRaises(ValueError):
            HedgeInstrument(
                "BANK_FORWARD",
                InstrumentKind.FORWARD,
                available=True,
                exclusion_reasons=("담보 미보유",),
            )

    def test_negative_cost_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HedgeInstrument(
                "KSURE_FX",
                InstrumentKind.KSURE_FX_INSURANCE,
                available=True,
                cost_rate=Decimal("-0.001"),
            )


class HedgeGuardTests(unittest.TestCase):
    def test_forward_is_not_offered_without_collateral(self) -> None:
        candidates = (FORWARD_WITHOUT_COLLATERAL, KSURE)

        self.assertEqual((KSURE,), usable_instruments(candidates))

    def test_exclusion_reasons_survive_for_the_response(self) -> None:
        blocked = excluded_instruments((FORWARD_WITHOUT_COLLATERAL, KSURE))

        self.assertEqual(1, len(blocked))
        self.assertEqual(("담보 또는 신용라인 미보유",), blocked[0].exclusion_reasons)

    def test_optimizer_boundary_rejects_unavailable_instrument(self) -> None:
        with self.assertRaises(UnavailableInstrumentError) as caught:
            assert_all_available((KSURE, FORWARD_WITHOUT_COLLATERAL))

        self.assertIn("BANK_FORWARD", str(caught.exception))
        self.assertIn("담보 또는 신용라인 미보유", str(caught.exception))

    def test_filtered_candidates_pass_the_boundary(self) -> None:
        candidates = (FORWARD_WITHOUT_COLLATERAL, KSURE)

        assert_all_available(usable_instruments(candidates))


if __name__ == "__main__":
    unittest.main()
