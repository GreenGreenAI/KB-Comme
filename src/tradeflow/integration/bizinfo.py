"""Official Bizinfo support-program API adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar

from tradeflow.domain.datasets import parse_bizinfo_support_payload
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot

ENDPOINT = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
SOURCE_ID = "BIZINFO_SUPPORT_API"
API_KEY_ENV = "BIZINFO_API_KEY"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


class BizinfoError(RuntimeError):
    pass


class BizinfoSupportAdapter:
    adapter_key: ClassVar[str] = "bizinfo_support"

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
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Bizinfo endpoint must be an absolute HTTPS URL")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_segment(source_id, "source_id")
        self.source_id = source_id
        self._api_key = api_key
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
        category_code: str | None = None,
        hashtags: tuple[str, ...] = (),
        page_size: int = 100,
        page_index: int = 1,
    ) -> dict[str, Any]:
        if page_size <= 0 or page_index <= 0:
            raise ValueError("page_size and page_index must be positive")
        key = self._api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise BizinfoError(f"{API_KEY_ENV} is not set")
        params = {
            "crtfcKey": key,
            "dataType": "json",
            "pageUnit": str(page_size),
            "pageIndex": str(page_index),
        }
        if category_code:
            params["searchLclasId"] = category_code
        if hashtags:
            params["hashtags"] = ",".join(hashtags)
        url = f"{self._endpoint}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url, headers={"Accept": "application/json"}, method="GET"
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise BizinfoError(f"Bizinfo returned HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise BizinfoError("Bizinfo is unreachable") from None
        if len(raw) > self._max_bytes:
            raise BizinfoError("Bizinfo response exceeds the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BizinfoError("Bizinfo did not return valid UTF-8 JSON") from None
        try:
            parse_bizinfo_support_payload(payload)
        except ValueError as exc:
            raise BizinfoError(str(exc)) from None
        return payload

    def collect(
        self,
        root: Path | str,
        *,
        retrieved_at: datetime | None = None,
        **filters: Any,
    ) -> Path:
        payload = self.fetch(**filters)
        retrieved = require_aware(
            retrieved_at or datetime.now(timezone.utc), "retrieved_at"
        )
        version = retrieved.astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        return write_snapshot(
            root,
            build_envelope(
                source_id=self.source_id,
                version=version,
                observed_at=retrieved,
                retrieved_at=retrieved,
                payload=payload,
            ),
        )
