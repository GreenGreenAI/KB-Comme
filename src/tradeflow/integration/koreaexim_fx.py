"""Official Korea Eximbank AP01 multi-currency reference-rate adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar

from tradeflow.domain.datasets import (
    DatasetContractError,
    ReferenceFxCatalog,
    parse_koreaexim_reference_fx_payload,
)
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot


ENDPOINT = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"
SOURCE_ID = "KOREAEXIM_REFERENCE_FX"
API_KEY_ENV = "KOREAEXIM_API_KEY"
DATA_CODE = "AP01"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
KST = timezone(timedelta(hours=9))


class KoreaEximFxError(RuntimeError):
    """Safe-to-report acquisition or official response-contract failure."""


class KoreaEximFxAdapter:
    adapter_key: ClassVar[str] = "koreaexim_reference_fx"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        source_id: str = SOURCE_ID,
        endpoint: str = ENDPOINT,
        timeout: float = 30,
        max_bytes: int = DEFAULT_MAX_BYTES,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("Korea Eximbank endpoint must be an absolute HTTPS URL")
        if parsed.query or parsed.fragment:
            raise ValueError("Korea Eximbank endpoint must not contain query or fragment")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_segment(source_id, "source_id")
        self._api_key = api_key
        self.source_id = source_id
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(endpoint=<redacted>, "
            f"source_id={self.source_id!r})"
        )

    def fetch(
        self,
        *,
        search_date: date,
    ) -> tuple[ReferenceFxCatalog, dict[str, Any]]:
        if not isinstance(search_date, date) or isinstance(search_date, datetime):
            raise TypeError("search_date must be a date")
        key = self._api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise KoreaEximFxError(f"{API_KEY_ENV} is not set")
        query = urllib.parse.urlencode(
            {
                "authkey": key,
                "searchdate": search_date.strftime("%Y%m%d"),
                "data": DATA_CODE,
            }
        )
        request = urllib.request.Request(
            f"{self._endpoint}?{query}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise KoreaEximFxError(
                f"Korea Eximbank returned HTTP {exc.code}"
            ) from None
        except urllib.error.URLError:
            raise KoreaEximFxError("Korea Eximbank is unreachable") from None
        if len(raw) > self._max_bytes:
            raise KoreaEximFxError("Korea Eximbank response exceeds the size limit")
        try:
            response_payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KoreaEximFxError(
                "Korea Eximbank did not return valid UTF-8 JSON"
            ) from None
        payload = {
            "schema_version": "1.0",
            "search_date": search_date.isoformat(),
            "response": response_payload,
        }
        try:
            catalog = parse_koreaexim_reference_fx_payload(payload)
        except DatasetContractError as exc:
            raise KoreaEximFxError(str(exc)) from None
        return catalog, payload

    def collect(
        self,
        root: Path | str,
        *,
        search_date: date,
        retrieved_at: datetime | None = None,
    ) -> Path:
        catalog, payload = self.fetch(search_date=search_date)
        retrieved = require_aware(
            retrieved_at or datetime.now(timezone.utc),
            "retrieved_at",
        )
        observed = datetime.combine(catalog.observed_on, time.min, tzinfo=KST)
        if observed > retrieved:
            raise KoreaEximFxError("search_date cannot be later than retrieved_at")
        version = (
            f"{catalog.observed_on.isoformat()}-"
            + retrieved.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        return write_snapshot(
            root,
            build_envelope(
                source_id=self.source_id,
                version=version,
                observed_at=observed,
                retrieved_at=retrieved,
                payload=payload,
            ),
        )
