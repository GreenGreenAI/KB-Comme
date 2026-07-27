"""Fail-closed ERP projections into the normalized TradeFlow trade feed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.domain.datasets import DatasetContractError, parse_trade_feed_payload
from tradeflow.domain.enums import PaymentMethod
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment


class ErpMappingError(ValueError):
    """A provider response cannot prove a normalized trade-feed value."""


@dataclass(frozen=True)
class ErpMappingContext:
    version: str
    observed_at: datetime
    opening_balances: Mapping[str, Decimal | str | int] = field(
        default_factory=dict
    )
    home_currency: str = "KRW"
    foreign_currency_only: bool = True
    default_payment_method: PaymentMethod | None = None

    def __post_init__(self) -> None:
        safe_segment(self.version, "version")
        require_aware(self.observed_at, "observed_at")
        home_currency = _currency(self.home_currency, "home_currency")
        if self.default_payment_method is not None and not isinstance(
            self.default_payment_method, PaymentMethod
        ):
            raise TypeError("default_payment_method must be a PaymentMethod")
        balances: dict[str, Decimal] = {}
        for raw_currency, raw_amount in self.opening_balances.items():
            currency = _currency(raw_currency, "opening_balances currency")
            if currency in balances:
                raise ErpMappingError(f"duplicate opening balance currency: {currency}")
            balances[currency] = _decimal(
                raw_amount, f"opening_balances.{currency}", signed=True
            )
        object.__setattr__(self, "home_currency", home_currency)
        object.__setattr__(self, "opening_balances", MappingProxyType(balances))


@dataclass(frozen=True)
class _MappedTrade:
    record: dict[str, Any]
    filtered_home_currency: bool = False
    filtered_zero_amount: bool = False
    filtered_closed: bool = False


class BusinessCentralInvoiceMapper:
    """Map Business Central v2 sales and purchase invoice collections.

    `remainingAmount` is official for sales invoices. The v2 purchase invoice
    resource exposes only invoice totals, so a customer connector must add
    `tradeflowRemainingAmount`; using the total as an open balance is refused.
    """

    mapper_key = "business_central_invoices_v1"

    def map(
        self,
        *,
        sales_invoices: Mapping[str, Any],
        purchase_invoices: Mapping[str, Any],
        context: ErpMappingContext,
    ) -> dict[str, Any]:
        sales = _odata_records(sales_invoices, "Business Central salesInvoices")
        purchases = _odata_records(
            purchase_invoices, "Business Central purchaseInvoices"
        )
        mapped = [
            *(self._map_invoice(item, "sales", context) for item in sales),
            *(self._map_invoice(item, "purchase", context) for item in purchases),
        ]
        return _build_feed(
            context=context,
            mapped=mapped,
            mapper_key=self.mapper_key,
            provider="microsoft_business_central",
            source_counts={"salesInvoices": len(sales), "purchaseInvoices": len(purchases)},
        )

    def _map_invoice(
        self,
        raw: Mapping[str, Any],
        entity: str,
        context: ErpMappingContext,
    ) -> _MappedTrade:
        if not isinstance(raw, Mapping):
            raise ErpMappingError(f"Business Central {entity} invoice must be an object")
        invoice_id = _text(raw, "id", f"Business Central {entity} invoice")
        case_id = f"BC-{entity.upper()}-{invoice_id}"
        try:
            safe_segment(case_id, "case_id")
        except ValueError as exc:
            raise ErpMappingError(str(exc)) from None

        raw_status = raw.get("status")
        if raw_status is not None and not isinstance(raw_status, str):
            raise ErpMappingError(f"{case_id}.status must be text")
        status = (raw_status or "").strip().lower()
        allowed_statuses = {
            "",
            "draft",
            "in review",
            "open",
            "paid",
            "canceled",
            "corrective",
        }
        if status not in allowed_statuses:
            raise ErpMappingError(f"{case_id}.status is unsupported: {status!r}")
        if status != "open":
            return _MappedTrade({}, filtered_closed=True)

        currency = _currency(_text(raw, "currencyCode", case_id), f"{case_id}.currencyCode")
        if context.foreign_currency_only and currency == context.home_currency:
            return _MappedTrade({}, filtered_home_currency=True)

        amount_field = (
            "remainingAmount" if entity == "sales" else "tradeflowRemainingAmount"
        )
        if amount_field not in raw:
            if entity == "purchase":
                raise ErpMappingError(
                    f"{case_id} requires tradeflowRemainingAmount; "
                    "totalAmountIncludingTax is not an open balance"
                )
            raise ErpMappingError(f"{case_id}.{amount_field} is required")
        amount = _decimal(raw[amount_field], f"{case_id}.{amount_field}")
        if amount == 0:
            return _MappedTrade({}, filtered_zero_amount=True)

        due_date = _iso_date(raw.get("dueDate"), f"{case_id}.dueDate")
        payment_method = _payment_method(
            raw,
            "tradeflowPaymentMethod",
            context=context,
            prefix=case_id,
        )
        country_field = "sellToCountry" if entity == "sales" else "buyFromCountry"
        country = _optional_country(raw.get(country_field), f"{case_id}.{country_field}")
        last_modified = _optional_instant(
            raw.get("lastModifiedDateTime"), f"{case_id}.lastModifiedDateTime"
        )
        if last_modified is not None and last_modified > context.observed_at:
            raise ErpMappingError(f"{case_id} was modified after observed_at")
        direction = "export" if entity == "sales" else "import"
        return _MappedTrade(
            {
                "case_id": case_id,
                "direction": direction,
                "currency": currency,
                "amount": str(amount.copy_abs()),
                "expected_payment_date": due_date.isoformat(),
                "payment_method": payment_method.value,
                "counterparty_country": country,
                "confirmed": True,
                "attributes": {
                    "erp_provider": "microsoft_business_central",
                    "erp_entity": f"{entity}Invoice",
                    "erp_id": invoice_id,
                    "erp_number": _optional_text(raw.get("number")),
                    "erp_status": status,
                    "posting_date": _optional_date_text(raw.get("postingDate"), case_id),
                    "invoice_date": _optional_date_text(raw.get("invoiceDate"), case_id),
                    "last_modified_at": (
                        last_modified.isoformat() if last_modified else None
                    ),
                },
            }
        )


class SapReceivablePayableMapper:
    """Map SAP S/4HANA Receivable Payable Item CDS/OData rows."""

    mapper_key = "sap_receivable_payable_items_v1"

    def map(
        self,
        *,
        items: Mapping[str, Any],
        context: ErpMappingContext,
    ) -> dict[str, Any]:
        records = _odata_records(items, "SAP Receivable Payable Item")
        mapped = [self._map_item(item, context) for item in records]
        return _build_feed(
            context=context,
            mapped=mapped,
            mapper_key=self.mapper_key,
            provider="sap_s4hana",
            source_counts={"receivablePayableItems": len(records)},
        )

    def _map_item(
        self,
        raw: Mapping[str, Any],
        context: ErpMappingContext,
    ) -> _MappedTrade:
        if not isinstance(raw, Mapping):
            raise ErpMappingError("SAP receivable/payable item must be an object")
        company = _text(raw, "CompanyCode", "SAP item")
        fiscal_year = _text(raw, "FiscalYear", "SAP item")
        document = _text(raw, "AccountingDocument", "SAP item")
        item = _text(raw, "AccountingDocumentItem", "SAP item")
        case_id = f"SAP-{company}-{fiscal_year}-{document}-{item}"
        try:
            safe_segment(case_id, "case_id")
        except ValueError as exc:
            raise ErpMappingError(str(exc)) from None

        cleared = _boolean(raw, "RblPyblItemIsCleared", case_id)
        obsolete = _boolean(raw, "RblPyblItemIsObsolete", case_id)
        if cleared or obsolete:
            return _MappedTrade({}, filtered_closed=True)

        customer = _optional_text(raw.get("Customer"))
        supplier = _optional_text(raw.get("Supplier"))
        if bool(customer) == bool(supplier):
            raise ErpMappingError(
                f"{case_id} must identify exactly one Customer or Supplier"
            )
        direction = "export" if customer else "import"
        currency = _currency(
            _text(raw, "TransactionCurrency", case_id),
            f"{case_id}.TransactionCurrency",
        )
        if context.foreign_currency_only and currency == context.home_currency:
            return _MappedTrade({}, filtered_home_currency=True)
        amount = _decimal(
            raw.get("AmountInTransactionCurrency"),
            f"{case_id}.AmountInTransactionCurrency",
            absolute=True,
        )
        if amount == 0:
            return _MappedTrade({}, filtered_zero_amount=True)
        due_date = _iso_date(raw.get("NetDueDate"), f"{case_id}.NetDueDate")
        payment_method = _payment_method(
            raw,
            "TradeflowPaymentMethod",
            context=context,
            prefix=case_id,
        )
        country = _optional_country(
            raw.get("CustomerSupplierCountry"),
            f"{case_id}.CustomerSupplierCountry",
        )
        return _MappedTrade(
            {
                "case_id": case_id,
                "direction": direction,
                "currency": currency,
                "amount": str(amount.copy_abs()),
                "expected_payment_date": due_date.isoformat(),
                "payment_method": payment_method.value,
                "counterparty_country": country,
                "confirmed": True,
                "attributes": {
                    "erp_provider": "sap_s4hana",
                    "erp_entity": "ReceivablePayableItem",
                    "company_code": company,
                    "fiscal_year": fiscal_year,
                    "accounting_document": document,
                    "accounting_document_item": item,
                    "business_partner": customer or supplier,
                    "posting_date": _optional_date_text(
                        raw.get("PostingDate"), case_id
                    ),
                    "original_reference_document": _optional_text(
                        raw.get("OriginalReferenceDocument")
                    ),
                },
            }
        )


def _build_feed(
    *,
    context: ErpMappingContext,
    mapped: list[_MappedTrade],
    mapper_key: str,
    provider: str,
    source_counts: Mapping[str, int],
) -> dict[str, Any]:
    trades = [item.record for item in mapped if item.record]
    if not trades:
        raise ErpMappingError("ERP response contains no usable foreign-currency open items")
    ids = [item["case_id"] for item in trades]
    if len(ids) != len(set(ids)):
        raise ErpMappingError("ERP response produces duplicate case_id values")
    balances = {
        currency: str(amount)
        for currency, amount in context.opening_balances.items()
        if not context.foreign_currency_only or currency != context.home_currency
    }
    document = {
        "schema_version": "1.0",
        "version": context.version,
        "observed_at": context.observed_at.isoformat(),
        "opening_balances": balances,
        "trades": trades,
        "mapping_metadata": {
            "mapper_key": mapper_key,
            "provider": provider,
            "source_counts": dict(source_counts),
            "mapped_count": len(trades),
            "filtered_closed_count": sum(item.filtered_closed for item in mapped),
            "filtered_home_currency_count": sum(
                item.filtered_home_currency for item in mapped
            ),
            "filtered_zero_amount_count": sum(
                item.filtered_zero_amount for item in mapped
            ),
        },
    }
    try:
        parse_trade_feed_payload(document)
    except DatasetContractError as exc:
        raise ErpMappingError(str(exc)) from None
    return document


def _odata_records(document: Mapping[str, Any], label: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(document, Mapping):
        raise ErpMappingError(f"{label} response must be an object")
    if document.get("@odata.nextLink"):
        raise ErpMappingError(f"{label} response is paginated and incomplete")
    if "value" in document:
        records = document["value"]
    else:
        body = document.get("d")
        if not isinstance(body, Mapping):
            raise ErpMappingError(f"{label} response has no OData collection")
        if body.get("__next"):
            raise ErpMappingError(f"{label} response is paginated and incomplete")
        records = body.get("results")
    if not isinstance(records, list):
        raise ErpMappingError(f"{label} collection must be an array")
    if not all(isinstance(item, Mapping) for item in records):
        raise ErpMappingError(f"{label} collection contains a non-object item")
    return tuple(records)


def _text(document: Mapping[str, Any], field_name: str, prefix: str) -> str:
    value = document.get(field_name)
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ErpMappingError(f"{prefix}.{field_name} must be text")
    text = str(value).strip()
    if not text:
        raise ErpMappingError(f"{prefix}.{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ErpMappingError("optional ERP text field has an invalid type")
    return str(value).strip() or None


def _decimal(
    value: Any,
    field_name: str,
    *,
    signed: bool = False,
    absolute: bool = False,
) -> Decimal:
    if signed and absolute:
        raise ValueError("signed and absolute decimal modes are mutually exclusive")
    if isinstance(value, bool) or isinstance(value, float) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ErpMappingError(
            f"{field_name} must be a decimal string, integer, or Decimal"
        )
    try:
        result = Decimal(str(value).strip())
    except InvalidOperation:
        raise ErpMappingError(f"{field_name} is not a valid decimal") from None
    if not result.is_finite():
        raise ErpMappingError(f"{field_name} must be finite")
    if result < 0 and absolute:
        result = result.copy_abs()
    elif result < 0 and not signed:
        raise ErpMappingError(f"{field_name} must not be negative")
    return result


def _currency(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ErpMappingError(f"{field_name} must be an ISO 4217 code")
    result = value.strip().upper()
    if len(result) != 3 or not result.isalpha() or not result.isascii():
        raise ErpMappingError(f"{field_name} must be a three-letter ISO 4217 code")
    return result


def _iso_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise ErpMappingError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ErpMappingError(f"{field_name} must be an ISO date") from None


def _optional_date_text(value: Any, prefix: str) -> str | None:
    if value is None or value == "":
        return None
    return _iso_date(value, f"{prefix}.date").isoformat()


def _optional_instant(value: Any, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ErpMappingError(f"{field_name} must be an ISO datetime")
    try:
        return require_aware(
            datetime.fromisoformat(value.replace("Z", "+00:00")), field_name
        )
    except ValueError:
        raise ErpMappingError(f"{field_name} must include a timezone offset") from None


def _boolean(document: Mapping[str, Any], field_name: str, prefix: str) -> bool:
    value = document.get(field_name)
    if not isinstance(value, bool):
        raise ErpMappingError(f"{prefix}.{field_name} must be boolean")
    return value


def _payment_method(
    document: Mapping[str, Any],
    field_name: str,
    *,
    context: ErpMappingContext,
    prefix: str,
) -> PaymentMethod:
    raw = document.get(field_name)
    if raw is None or raw == "":
        if context.default_payment_method is None:
            raise ErpMappingError(
                f"{prefix}.{field_name} is required when no explicit default is configured"
            )
        return context.default_payment_method
    if not isinstance(raw, str):
        raise ErpMappingError(f"{prefix}.{field_name} must be text")
    try:
        return PaymentMethod(raw.strip().lower())
    except ValueError:
        raise ErpMappingError(f"{prefix}.{field_name} is unsupported") from None


def _optional_country(value: Any, field_name: str) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    result = text.upper()
    if len(result) != 2 or not result.isalpha() or not result.isascii():
        raise ErpMappingError(f"{field_name} must be an ISO 3166-1 alpha-2 code")
    return result
