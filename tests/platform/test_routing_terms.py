import unittest
from datetime import date
from decimal import Decimal

from tradeflow.agent.routing import derive_payment_terms, derive_structure
from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram

COMPANY = CompanyProfile(company_id="C", name="시험용")


def _program(*cases: TradeCase) -> TradeProgram:
    return TradeProgram(program_id="P", company=COMPANY, cases=cases)


def _case(cid: str, shipment: str | None, payment: str) -> TradeCase:
    return TradeCase(
        case_id=cid,
        direction=TradeDirection.EXPORT,
        currency="USD",
        amount=Decimal("100000"),
        expected_payment_date=date.fromisoformat(payment),
        payment_method=PaymentMethod.TT,
        attributes={"expected_shipment_date": shipment} if shipment else {},
    )


class PaymentTermTests(unittest.TestCase):
    """§5.4 asks whether the payment term is within two years, and the company
    already said when it ships and when it is paid."""

    def test_the_term_is_the_gap_between_the_two_dates(self) -> None:
        terms = derive_payment_terms(
            _program(_case("A", "2026-09-01", "2026-10-24"))
        )

        self.assertEqual({"trade.payment_term_days": 53}, terms)

    def test_a_blank_shipment_date_produces_nothing(self) -> None:
        """Reporting the fact as missing is the right answer. A term computed
        from a date nobody gave would be manufactured out of a blank field —
        and it is the input that gets asked for, not the term."""
        self.assertEqual({}, derive_payment_terms(_program(_case("A", None, "2026-10-24"))))

    def test_a_prepayment_is_not_a_term(self) -> None:
        """Payment before shipment is §5.5's question, and `derive_structure`
        keeps that sign. The two must not both claim the same trade."""
        prepaid = _program(_case("A", "2026-10-24", "2026-09-01"))

        self.assertEqual({}, derive_payment_terms(prepaid))
        self.assertEqual(
            {"trade.days_before_shipment": 53}, derive_structure(prepaid)
        )

    def test_the_longest_term_decides(self) -> None:
        """It is the one that can cross the limit, and a shorter trade on the
        same program cannot make it safe."""
        terms = derive_payment_terms(
            _program(
                _case("A", "2026-09-01", "2026-10-24"),
                _case("B", "2026-09-01", "2028-12-01"),
            )
        )

        self.assertEqual(822, terms["trade.payment_term_days"])


if __name__ == "__main__":
    unittest.main()
