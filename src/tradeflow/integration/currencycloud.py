"""Currencycloud Demo indicative future-date quote adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, ClassVar

from tradeflow.domain.datasets import (
    DatasetContractError,
    parse_provider_indicative_forward_quote_payload,
)
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import content_hash, safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot


DEMO_BASE = "https://devapi.currencycloud.com"
SOURCE_ID = "CURRENCYCLOUD_DEMO_FORWARD_QUOTES"
LOGIN_ID_ENV = "CURRENCYCLOUD_DEMO_LOGIN_ID"
API_KEY_ENV = "CURRENCYCLOUD_DEMO_API_KEY"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024


class CurrencycloudError(RuntimeError):
    """Safe-to-report demo authentication, transport or contract failure."""


class CurrencycloudDemoForwardQuoteAdapter:
    adapter_key: ClassVar[str] = "currencycloud_demo_forward_quote"

    def __init__(
        self,
        *,
        tenant_id: str,
        company_id: str,
        login_id: str | None = None,
        api_key: str | None = None,
        source_id: str = SOURCE_ID,
        base_url: str = DEMO_BASE,
        timeout: float = 30,
        max_bytes: int = DEFAULT_MAX_BYTES,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or parsed.netloc != "devapi.currencycloud.com":
            raise ValueError("Currencycloud Demo base URL must be official HTTPS")
        if not tenant_id.strip() or not company_id.strip():
            raise ValueError("tenant_id and company_id are required")
        safe_segment(source_id, "source_id")
        self.source_id = source_id
        self.tenant_id = tenant_id.strip()
        self.company_id = company_id.strip()
        self._login_id = login_id
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url=<official-demo>, "
            "tenant_id=<redacted>, company_id=<redacted>)"
        )

    def _request(
        self,
        path: str,
        *,
        method: str,
        form: dict[str, str] | None = None,
        token: str | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        body = urllib.parse.urlencode(form or {}).encode("ascii") if form else None
        headers = {"Accept": "application/json"}
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if token:
            headers["X-Auth-Token"] = token
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise CurrencycloudError(
                f"Currencycloud Demo returned HTTP {exc.code}"
            ) from None
        except urllib.error.URLError:
            raise CurrencycloudError("Currencycloud Demo is unreachable") from None
        if len(raw) > self._max_bytes:
            raise CurrencycloudError("Currencycloud Demo response is too large")
        if allow_empty and not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CurrencycloudError(
                "Currencycloud Demo returned invalid JSON"
            ) from None
        if not isinstance(payload, dict):
            raise CurrencycloudError("Currencycloud Demo response must be an object")
        return payload

    def authenticate(self) -> str:
        login_id = self._login_id or os.environ.get(LOGIN_ID_ENV)
        api_key = self._api_key or os.environ.get(API_KEY_ENV)
        if not login_id or not api_key:
            raise CurrencycloudError(
                f"{LOGIN_ID_ENV} and {API_KEY_ENV} must be configured"
            )
        payload = self._request(
            "/v2/authenticate/api",
            method="POST",
            form={"login_id": login_id, "api_key": api_key},
        )
        token = payload.get("auth_token")
        if not isinstance(token, str) or not token:
            raise CurrencycloudError("Currencycloud Demo omitted auth_token")
        return token

    def close_session(self, token: str) -> None:
        """Close a short-lived demo API session without exposing its token."""
        self._request(
            "/v2/authenticate/close_session",
            method="POST",
            token=token,
            allow_empty=True,
        )

    def fetch(
        self,
        *,
        buy_currency: str,
        sell_currency: str,
        amount: Decimal | str,
        fixed_side: str,
        conversion_date: date,
        case_ids: tuple[str, ...],
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        observed = require_aware(
            observed_at or datetime.now(timezone.utc), "observed_at"
        )
        buy = buy_currency.strip().upper()
        sell = sell_currency.strip().upper()
        if fixed_side not in {"buy", "sell"}:
            raise ValueError("fixed_side must be buy or sell")
        if conversion_date <= observed.date():
            raise ValueError("conversion_date must be in the future")
        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise ValueError("case_ids must be non-empty and unique")
        try:
            quantity = Decimal(str(amount))
        except InvalidOperation:
            raise ValueError("amount must be decimal") from None
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("amount must be positive")

        token = self.authenticate()
        try:
            params = urllib.parse.urlencode(
                {
                    "buy_currency": buy,
                    "sell_currency": sell,
                    "amount": str(quantity),
                    "fixed_side": fixed_side,
                    "conversion_date": conversion_date.isoformat(),
                }
            )
            raw = self._request(
                f"/v2/rates/detailed?{params}",
                method="GET",
                token=token,
            )
        finally:
            self.close_session(token)
        economic = {
            key: raw.get(key)
            for key in (
                "currency_pair",
                "client_buy_currency",
                "client_sell_currency",
                "client_buy_amount",
                "client_sell_amount",
                "fixed_side",
                "client_rate",
                "core_rate",
                "mid_market_rate",
                "conversion_date",
                "settlement_cut_off_time",
            )
        }
        record_hash = content_hash(economic)
        response_conversion_date = str(
            raw.get("conversion_date", conversion_date.isoformat())
        )[:10]
        payload = {
            "schema_version": "1.0",
            "dataset_id": (
                "currencycloud-demo-"
                + observed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            ),
            "tenant_id": self.tenant_id,
            "provider_id": "CURRENCYCLOUD",
            "environment": "demo",
            "retention_class": "tenant_private_financial",
            "records": [
                {
                    "record_id": "cc-" + record_hash.removeprefix("sha256:")[:24],
                    "company_id": self.company_id,
                    "case_ids": list(case_ids),
                    "buy_currency": raw.get("client_buy_currency", buy),
                    "sell_currency": raw.get("client_sell_currency", sell),
                    "fixed_side": raw.get("fixed_side", fixed_side),
                    "amount": str(quantity),
                    "client_buy_amount": str(raw.get("client_buy_amount", "")),
                    "client_sell_amount": str(raw.get("client_sell_amount", "")),
                    "client_rate": str(raw.get("client_rate", "")),
                    "core_rate": str(raw.get("core_rate", "")),
                    "mid_market_rate": (
                        None
                        if raw.get("mid_market_rate") is None
                        else str(raw["mid_market_rate"])
                    ),
                    "conversion_date": response_conversion_date,
                    "observed_at": observed.isoformat(),
                    "quote_basis": "provider_indicative_forward_quote",
                    "booking_required": True,
                    "evidence_content_hash": record_hash,
                }
            ],
        }
        try:
            parse_provider_indicative_forward_quote_payload(payload)
        except DatasetContractError as exc:
            raise CurrencycloudError(str(exc)) from None
        return payload

    def collect(
        self,
        root: Path | str,
        *,
        retrieved_at: datetime | None = None,
        **parameters: Any,
    ) -> Path:
        retrieved = require_aware(
            retrieved_at or datetime.now(timezone.utc), "retrieved_at"
        )
        payload = self.fetch(observed_at=retrieved, **parameters)
        return write_snapshot(
            root,
            build_envelope(
                source_id=self.source_id,
                version=payload["dataset_id"],
                observed_at=retrieved,
                retrieved_at=retrieved,
                payload=payload,
            ),
        )
