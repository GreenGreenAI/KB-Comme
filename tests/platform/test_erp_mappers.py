import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tradeflow.domain.datasets import parse_trade_feed_payload
from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.integration.erp_mappers import (
    BusinessCentralInvoiceMapper,
    ErpMappingContext,
    ErpMappingError,
    SapReceivablePayableMapper,
)

KST = timezone(timedelta(hours=9))
OBSERVED = datetime(2026, 7, 27, 9, tzinfo=KST)


def _context(**changes) -> ErpMappingContext:
    values = {
        "version": "erp-20260727-090000",
        "observed_at": OBSERVED,
        "opening_balances": {"USD": "1200.50", "KRW": "500000"},
        "default_payment_method": PaymentMethod.TT,
    }
    values.update(changes)
    return ErpMappingContext(**values)


def _sales(**changes) -> dict:
    record = {
        "id": "sales-1",
        "number": "S-100",
        "status": "Open",
        "currencyCode": "USD",
        "remainingAmount": Decimal("10000.25"),
        "dueDate": "2026-08-31",
        "sellToCountry": "US",
        "postingDate": "2026-07-01",
        "invoiceDate": "2026-06-30",
        "lastModifiedDateTime": "2026-07-27T08:00:00+09:00",
    }
    record.update(changes)
    return record


def _purchase(**changes) -> dict:
    record = {
        "id": "purchase-1",
        "number": "P-100",
        "status": "Open",
        "currencyCode": "EUR",
        "totalAmountIncludingTax": Decimal("9000"),
        "tradeflowRemainingAmount": Decimal("7000.50"),
        "dueDate": "2026-08-20",
        "buyFromCountry": "DE",
        "postingDate": "2026-07-02",
        "invoiceDate": "2026-07-01",
        "lastModifiedDateTime": "2026-07-27T07:00:00+09:00",
        "tradeflowPaymentMethod": "lc",
    }
    record.update(changes)
    return record


def _sap(**changes) -> dict:
    record = {
        "CompanyCode": "1000",
        "FiscalYear": "2026",
        "AccountingDocument": "1900000001",
        "AccountingDocumentItem": "001",
        "RblPyblItemIsCleared": False,
        "RblPyblItemIsObsolete": False,
        "Customer": "C100",
        "Supplier": "",
        "TransactionCurrency": "USD",
        "AmountInTransactionCurrency": "25000.75",
        "NetDueDate": "2026-09-15",
        "PostingDate": "2026-07-20",
        "CustomerSupplierCountry": "US",
        "OriginalReferenceDocument": "INV-100",
    }
    record.update(changes)
    return record


class ErpMappingContextTests(unittest.TestCase):
    def test_context_normalizes_and_freezes_balances(self) -> None:
        balances = {"usd": "10.25"}
        context = _context(opening_balances=balances)
        balances["usd"] = "999"

        self.assertEqual(Decimal("10.25"), context.opening_balances["USD"])
        with self.assertRaises(TypeError):
            context.opening_balances["EUR"] = Decimal("1")

    def test_context_rejects_float_money_and_untyped_payment_default(self) -> None:
        with self.assertRaisesRegex(ErpMappingError, "decimal string"):
            _context(opening_balances={"USD": 0.1})
        with self.assertRaisesRegex(TypeError, "PaymentMethod"):
            _context(default_payment_method="tt")


class BusinessCentralMapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = BusinessCentralInvoiceMapper()

    def test_open_sales_and_purchase_invoices_become_exact_trade_cases(self) -> None:
        sales = {
            "value": [
                _sales(),
                _sales(id="paid", status="Paid"),
                _sales(id="home", currencyCode="KRW"),
                _sales(id="zero", remainingAmount="0"),
            ]
        }
        purchases = {"value": [_purchase()]}

        document = self.mapper.map(
            sales_invoices=sales,
            purchase_invoices=purchases,
            context=_context(),
        )
        feed = parse_trade_feed_payload(document)

        self.assertEqual(2, len(feed.cases))
        export, imported = feed.cases
        self.assertEqual(TradeDirection.EXPORT, export.direction)
        self.assertEqual(Decimal("10000.25"), export.amount)
        self.assertEqual("US", export.counterparty_country)
        self.assertEqual(TradeDirection.IMPORT, imported.direction)
        self.assertEqual(Decimal("7000.50"), imported.amount)
        self.assertEqual(PaymentMethod.LC, imported.payment_method)
        self.assertEqual({"USD": Decimal("1200.50")}, dict(feed.opening_balances))
        metadata = document["mapping_metadata"]
        self.assertEqual(2, metadata["mapped_count"])
        self.assertEqual(1, metadata["filtered_closed_count"])
        self.assertEqual(1, metadata["filtered_home_currency_count"])
        self.assertEqual(1, metadata["filtered_zero_amount_count"])

    def test_purchase_total_is_never_substituted_for_remaining_amount(self) -> None:
        purchase = _purchase()
        del purchase["tradeflowRemainingAmount"]

        with self.assertRaisesRegex(
            ErpMappingError, "totalAmountIncludingTax is not an open balance"
        ):
            self.mapper.map(
                sales_invoices={"value": []},
                purchase_invoices={"value": [purchase]},
                context=_context(),
            )

    def test_payment_method_must_be_explicit_when_no_policy_default_exists(self) -> None:
        with self.assertRaisesRegex(ErpMappingError, "PaymentMethod is required"):
            self.mapper.map(
                sales_invoices={"value": [_sales()]},
                purchase_invoices={"value": []},
                context=_context(default_payment_method=None),
            )

        document = self.mapper.map(
            sales_invoices={
                "value": [_sales(tradeflowPaymentMethod="da")]
            },
            purchase_invoices={"value": []},
            context=_context(default_payment_method=None),
        )
        self.assertEqual("da", document["trades"][0]["payment_method"])

    def test_partial_pages_float_money_and_future_modification_fail_closed(self) -> None:
        with self.assertRaisesRegex(ErpMappingError, "paginated and incomplete"):
            self.mapper.map(
                sales_invoices={"value": [_sales()], "@odata.nextLink": "next"},
                purchase_invoices={"value": []},
                context=_context(),
            )
        with self.assertRaisesRegex(ErpMappingError, "decimal string"):
            self.mapper.map(
                sales_invoices={"value": [_sales(remainingAmount=0.1)]},
                purchase_invoices={"value": []},
                context=_context(),
            )
        with self.assertRaisesRegex(ErpMappingError, "after observed_at"):
            self.mapper.map(
                sales_invoices={
                    "value": [
                        _sales(lastModifiedDateTime="2026-07-27T09:01:00+09:00")
                    ]
                },
                purchase_invoices={"value": []},
                context=_context(),
            )

        with self.assertRaisesRegex(ErpMappingError, "must not be negative"):
            self.mapper.map(
                sales_invoices={
                    "value": [_sales(remainingAmount="-100.00")]
                },
                purchase_invoices={"value": []},
                context=_context(),
            )

    def test_duplicate_ids_and_unknown_status_are_rejected(self) -> None:
        with self.assertRaisesRegex(ErpMappingError, "duplicate case_id"):
            self.mapper.map(
                sales_invoices={"value": [_sales(), _sales()]},
                purchase_invoices={"value": []},
                context=_context(),
            )
        with self.assertRaisesRegex(ErpMappingError, "status is unsupported"):
            self.mapper.map(
                sales_invoices={"value": [_sales(status="Mystery")]},
                purchase_invoices={"value": []},
                context=_context(),
            )


class SapMapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = SapReceivablePayableMapper()

    def test_open_customer_and_supplier_items_map_by_account_role(self) -> None:
        items = {
            "d": {
                "results": [
                    _sap(),
                    _sap(
                        AccountingDocument="1900000002",
                        AccountingDocumentItem="002",
                        Customer="",
                        Supplier="V100",
                        TransactionCurrency="EUR",
                        AmountInTransactionCurrency="-9000.50",
                        CustomerSupplierCountry="DE",
                        TradeflowPaymentMethod="dp",
                    ),
                    _sap(
                        AccountingDocument="1900000003",
                        RblPyblItemIsCleared=True,
                    ),
                    _sap(
                        AccountingDocument="1900000004",
                        TransactionCurrency="KRW",
                    ),
                ]
            }
        }

        document = self.mapper.map(items=items, context=_context())
        feed = parse_trade_feed_payload(document)

        self.assertEqual(2, len(feed.cases))
        self.assertEqual(TradeDirection.EXPORT, feed.cases[0].direction)
        self.assertEqual(TradeDirection.IMPORT, feed.cases[1].direction)
        self.assertEqual(Decimal("9000.50"), feed.cases[1].amount)
        self.assertEqual(PaymentMethod.DP, feed.cases[1].payment_method)
        self.assertEqual(1, document["mapping_metadata"]["filtered_closed_count"])
        self.assertEqual(
            1, document["mapping_metadata"]["filtered_home_currency_count"]
        )

    def test_customer_or_supplier_must_be_unambiguous(self) -> None:
        for record in (
            _sap(Customer="", Supplier=""),
            _sap(Customer="C100", Supplier="V100"),
        ):
            with self.subTest(record=record):
                with self.assertRaisesRegex(ErpMappingError, "exactly one"):
                    self.mapper.map(
                        items={"value": [record]}, context=_context()
                    )

    def test_open_state_due_date_and_payment_method_are_not_inferred(self) -> None:
        missing_flag = _sap()
        del missing_flag["RblPyblItemIsCleared"]
        with self.assertRaisesRegex(ErpMappingError, "must be boolean"):
            self.mapper.map(items={"value": [missing_flag]}, context=_context())

        with self.assertRaisesRegex(ErpMappingError, "NetDueDate"):
            self.mapper.map(
                items={"value": [_sap(NetDueDate=None)]}, context=_context()
            )

        with self.assertRaisesRegex(ErpMappingError, "PaymentMethod is required"):
            self.mapper.map(
                items={"value": [_sap()]},
                context=_context(default_payment_method=None),
            )

    def test_v2_pagination_and_float_amount_are_rejected(self) -> None:
        with self.assertRaisesRegex(ErpMappingError, "paginated and incomplete"):
            self.mapper.map(
                items={"d": {"results": [_sap()], "__next": "next"}},
                context=_context(),
            )
        with self.assertRaisesRegex(ErpMappingError, "decimal string"):
            self.mapper.map(
                items={"value": [_sap(AmountInTransactionCurrency=0.1)]},
                context=_context(),
            )


if __name__ == "__main__":
    unittest.main()
