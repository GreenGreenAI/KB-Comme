"""Normalize LSEG FXall Cash RFQ FIX quotes into KB Comme's private contract.

This module deliberately does not implement a FIX session. Session onboarding,
counterparty permissions and credentials remain in the tenant connector. Only
the economic fields of an already authenticated Quote (S) message cross into
KB Comme.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from tradeflow.domain.snapshot_file import content_hash


class FxallQuoteError(ValueError):
    """A safe-to-report FXall message or mapping failure."""


@dataclass(frozen=True)
class FxallQuoteContext:
    tenant_id: str
    company_id: str
    provider_id: str
    case_ids: tuple[str, ...]
    record_id: str
    origin_spot_snapshot: Mapping[str, str]
    cost_rate: Decimal
    session_verified: bool


_ECONOMIC_TAGS = {
    "35",   # MsgType
    "15",   # Currency
    "38",   # OrderQty
    "54",   # Side
    "55",   # Symbol
    "60",   # TransactTime
    "62",   # ValidUntilTime
    "64",   # SettlDate
    "117",  # QuoteID
    "131",  # QuoteReqID
    "167",  # SecurityType
    "188",  # BidSpotRate
    "189",  # BidForwardPoints
    "190",  # OfferSpotRate
    "191",  # OfferForwardPoints
}


def parse_fix_fields(message: str | bytes) -> dict[str, str]:
    """Parse one flat FIX message and reject ambiguity.

    Repeating groups are intentionally unsupported: the MVP accepts one
    outright FXFWD Quote (S), not swaps, blocks or multi-leg structures.
    """
    if isinstance(message, bytes):
        try:
            text = message.decode("ascii")
        except UnicodeDecodeError:
            raise FxallQuoteError("FIX message must be ASCII") from None
    elif isinstance(message, str):
        text = message
    else:
        raise FxallQuoteError("FIX message must be text or bytes")

    delimiter = "\x01" if "\x01" in text else "|"
    fields: dict[str, str] = {}
    for item in text.strip().strip(delimiter).split(delimiter):
        if not item:
            continue
        if "=" not in item:
            raise FxallQuoteError("FIX field is missing '='")
        tag, value = item.split("=", 1)
        if not tag.isdigit() or not value:
            raise FxallQuoteError("FIX tag and value must be non-empty")
        if tag in fields:
            raise FxallQuoteError(f"duplicate FIX tag is unsupported: {tag}")
        fields[tag] = value
    if not fields:
        raise FxallQuoteError("FIX message is empty")
    return fields


def _required(fields: Mapping[str, str], tag: str, name: str) -> str:
    value = fields.get(tag)
    if not value:
        raise FxallQuoteError(f"missing FXall {name} tag {tag}")
    return value


def _decimal(value: str, name: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise FxallQuoteError(f"{name} must be decimal") from None
    if not result.is_finite() or (positive and result <= 0):
        raise FxallQuoteError(f"{name} must be finite and positive")
    return result


def _utc_timestamp(value: str, name: str) -> datetime:
    formats = ("%Y%m%d-%H:%M:%S.%f", "%Y%m%d-%H:%M:%S")
    for pattern in formats:
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise FxallQuoteError(f"{name} must be a FIX UTC timestamp")


def _settlement_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    except ValueError:
        raise FxallQuoteError("SettlDate must use YYYYMMDD") from None


def normalize_fxall_forward_quote(
    message: str | bytes,
    *,
    context: FxallQuoteContext,
) -> dict[str, object]:
    """Map an authenticated FXall outright forward quote to one record."""
    if not context.session_verified:
        raise FxallQuoteError("FXall session must be authenticated and verified")
    if not context.case_ids or len(set(context.case_ids)) != len(context.case_ids):
        raise FxallQuoteError("case_ids must be non-empty and unique")
    fields = parse_fix_fields(message)
    if _required(fields, "35", "MsgType") != "S":
        raise FxallQuoteError("only FXall Quote (S) messages are accepted")
    if _required(fields, "167", "SecurityType") != "FXFWD":
        raise FxallQuoteError("only outright FXFWD quotes are accepted")

    symbol = _required(fields, "55", "Symbol")
    parts = symbol.split("/")
    if len(parts) != 2 or any(len(item) != 3 or not item.isalpha() for item in parts):
        raise FxallQuoteError("Symbol must use AAA/BBB")
    base_currency, counter_currency = (item.upper() for item in parts)
    if _required(fields, "15", "Currency").upper() != base_currency:
        raise FxallQuoteError("MVP requires OrderQty in the base currency")

    side_tag = _required(fields, "54", "Side")
    if side_tag == "1":
        side, spot_tag, points_tag = "buy", "190", "191"
    elif side_tag == "2":
        side, spot_tag, points_tag = "sell", "188", "189"
    else:
        raise FxallQuoteError("Side must be client buy (1) or client sell (2)")

    notional = _decimal(
        _required(fields, "38", "OrderQty"),
        "OrderQty",
        positive=True,
    )
    spot = _decimal(_required(fields, spot_tag, "side spot rate"), "spot rate")
    points = _decimal(
        _required(fields, points_tag, "side forward points"),
        "forward points",
    )
    contract_rate = spot + points
    if contract_rate <= 0:
        raise FxallQuoteError("spot plus forward points must be positive")

    observed_at = _utc_timestamp(
        _required(fields, "60", "TransactTime"),
        "TransactTime",
    )
    valid_until = _utc_timestamp(
        _required(fields, "62", "ValidUntilTime"),
        "ValidUntilTime",
    )
    if valid_until < observed_at:
        raise FxallQuoteError("ValidUntilTime cannot precede TransactTime")

    evidence = {
        tag: fields[tag]
        for tag in sorted(_ECONOMIC_TAGS, key=int)
        if tag in fields
    }
    return {
        "record_id": context.record_id,
        "quote_id": _required(fields, "117", "QuoteID"),
        "provider_id": context.provider_id,
        "company_id": context.company_id,
        "case_ids": list(context.case_ids),
        "base_currency": base_currency,
        "counter_currency": counter_currency,
        "side": side,
        "notional_min": str(notional),
        "notional_max": str(notional),
        "contract_rate": str(contract_rate),
        "cost_rate": str(context.cost_rate),
        "settlement_date": _settlement_date(
            _required(fields, "64", "SettlDate")
        ),
        "observed_at": observed_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "quote_basis": "observed_forward_quote",
        "provider_verified": True,
        "company_applicable": True,
        "origin_spot_snapshot": dict(context.origin_spot_snapshot),
        "evidence_content_hash": content_hash(evidence),
    }


def build_fxall_forward_quote_payload(
    messages: Sequence[str | bytes],
    *,
    dataset_id: str,
    contexts: Sequence[FxallQuoteContext],
) -> dict[str, object]:
    """Build one existing-schema dataset from matched FIX messages/contexts."""
    if not messages or len(messages) != len(contexts):
        raise FxallQuoteError("messages and contexts must be non-empty and aligned")
    tenant_ids = {context.tenant_id for context in contexts}
    if len(tenant_ids) != 1:
        raise FxallQuoteError("one dataset cannot cross tenant boundaries")
    return {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "tenant_id": next(iter(tenant_ids)),
        "retention_class": "tenant_private_financial",
        "records": [
            normalize_fxall_forward_quote(message, context=context)
            for message, context in zip(messages, contexts, strict=True)
        ],
    }
