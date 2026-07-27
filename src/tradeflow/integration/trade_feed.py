"""Adapter for a normalized enterprise trade and cashflow JSON feed.

ERP-specific connectors should map their records to this small contract at the
network boundary. The raw JSON response is stored as evidence; parsing only
produces domain values for validation and does not rewrite the source payload.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import TradeCase
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot

DEFAULT_MAX_BYTES = 10 * 1024 * 1024


class TradeFeedError(RuntimeError):
    """A safe-to-report acquisition or contract failure."""


@dataclass(frozen=True)
class TradeFeedBatch:
    """Validated values plus the untouched payload they came from."""

    version: str
    observed_at: datetime
    cases: tuple[TradeCase, ...]
    opening_balances: Mapping[str, Decimal]
    raw_payload: dict[str, Any]


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TradeFeedError(f"{field} must be a non-empty string")
    return value.strip()


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise TradeFeedError(f"{field} must be a decimal string or number")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise TradeFeedError(f"{field} is not a valid decimal") from None


def parse_trade_feed(payload: Any) -> TradeFeedBatch:
    """Validate version 1 of the normalized feed and create domain values."""
    if not isinstance(payload, dict):
        raise TradeFeedError("feed root must be a JSON object")

    schema_version = payload.get("schema_version")
    if schema_version != "1.0":
        raise TradeFeedError(f"unsupported schema_version: {schema_version!r}")

    version = _required_text(payload, "version")
    try:
        safe_segment(version, "version")
    except ValueError as exc:
        raise TradeFeedError(str(exc)) from None
    observed_text = _required_text(payload, "observed_at")
    try:
        observed_at = require_aware(
            datetime.fromisoformat(observed_text.replace("Z", "+00:00")),
            "observed_at",
        )
    except ValueError as exc:
        raise TradeFeedError(f"invalid observed_at: {exc}") from None

    records = payload.get("trades")
    if not isinstance(records, list) or not records:
        raise TradeFeedError("trades must be a non-empty array")

    cases: list[TradeCase] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"trades[{index}]"
        if not isinstance(record, dict):
            raise TradeFeedError(f"{prefix} must be an object")
        case_id = _required_text(record, "case_id")
        if case_id in seen:
            raise TradeFeedError(f"duplicate case_id: {case_id}")
        seen.add(case_id)

        try:
            direction = TradeDirection(_required_text(record, "direction").lower())
            payment_method = PaymentMethod(
                _required_text(record, "payment_method").lower()
            )
            expected_payment_date = datetime.strptime(
                _required_text(record, "expected_payment_date"), "%Y-%m-%d"
            ).date()
        except ValueError as exc:
            raise TradeFeedError(f"{prefix} has an invalid enum or date: {exc}") from None

        confirmed = record.get("confirmed", True)
        if not isinstance(confirmed, bool):
            raise TradeFeedError(f"{prefix}.confirmed must be boolean")
        attributes = record.get("attributes", {})
        if not isinstance(attributes, dict):
            raise TradeFeedError(f"{prefix}.attributes must be an object")
        country = record.get("counterparty_country")
        if country is not None and not isinstance(country, str):
            raise TradeFeedError(f"{prefix}.counterparty_country must be a string")

        try:
            cases.append(
                TradeCase(
                    case_id=case_id,
                    direction=direction,
                    currency=_required_text(record, "currency"),
                    amount=_decimal(record.get("amount"), f"{prefix}.amount"),
                    expected_payment_date=expected_payment_date,
                    payment_method=payment_method,
                    counterparty_country=country,
                    confirmed=confirmed,
                    attributes=dict(attributes),
                )
            )
        except ValueError as exc:
            raise TradeFeedError(f"{prefix} is invalid: {exc}") from None

    raw_balances = payload.get("opening_balances", {})
    if not isinstance(raw_balances, dict):
        raise TradeFeedError("opening_balances must be an object")
    balances = {
        _required_text({"currency": currency}, "currency").upper(): _decimal(
            value, f"opening_balances.{currency}"
        )
        for currency, value in raw_balances.items()
    }

    return TradeFeedBatch(
        version=version,
        observed_at=observed_at,
        cases=tuple(cases),
        opening_balances=balances,
        raw_payload=payload,
    )


class JsonTradeFeedAdapter:
    """Read an HTTPS JSON feed using an optional bearer token."""

    def __init__(
        self,
        *,
        endpoint: str,
        source_id: str,
        bearer_token: str | None = None,
        timeout: float = 30,
        max_bytes: int = DEFAULT_MAX_BYTES,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("trade feed endpoint must be an absolute HTTPS URL")
        safe_segment(source_id, "source_id")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._endpoint = endpoint
        self.source_id = source_id
        self._bearer_token = bearer_token
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(endpoint=<redacted>, "
            f"source_id={self.source_id!r})"
        )

    def fetch(self) -> TradeFeedBatch:
        headers = {"Accept": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        request = urllib.request.Request(self._endpoint, headers=headers, method="GET")

        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise TradeFeedError(f"trade feed returned HTTP {exc.code}") from None
        except urllib.error.URLError:
            # Some URL handlers include the request URL in their reason. The
            # endpoint may carry a tenant identifier or legacy query secret.
            raise TradeFeedError("trade feed is unreachable") from None

        if len(raw) > self._max_bytes:
            raise TradeFeedError(
                f"trade feed exceeds the {self._max_bytes}-byte response limit"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TradeFeedError("trade feed did not return valid UTF-8 JSON") from None
        return parse_trade_feed(payload)

    def collect(
        self,
        root: Path | str,
        *,
        retrieved_at: datetime | None = None,
    ) -> Path:
        batch = self.fetch()
        retrieved = retrieved_at or datetime.now(timezone.utc)
        require_aware(retrieved, "retrieved_at")
        if batch.observed_at > retrieved:
            raise TradeFeedError("observed_at cannot be later than retrieved_at")
        envelope = build_envelope(
            source_id=self.source_id,
            version=batch.version,
            observed_at=batch.observed_at,
            retrieved_at=retrieved,
            payload=batch.raw_payload,
        )
        return write_snapshot(root, envelope)
