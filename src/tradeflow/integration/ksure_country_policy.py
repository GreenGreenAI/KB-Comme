"""Current K-SURE country-policy catalog from the official K-Sight service."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar

from tradeflow.domain.datasets import parse_ksure_country_policy_payload
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot

ENDPOINT = "https://ksight.ksure.or.kr/api/rsrch/selectFilterLst"
DIRECTORY_ENDPOINT = "https://ksight.ksure.or.kr/api/rsrch/getAutoLst"
REFERER = "https://ksight.ksure.or.kr/rsrch/nation/nationView"
SOURCE_ID = "KSURE_COUNTRY_POLICY_API"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024


class KsureCountryPolicyError(RuntimeError):
    """The official country-policy catalog could not be obtained or verified."""


class KsureCountryPolicyAdapter:
    adapter_key: ClassVar[str] = "ksure_country_policy"

    def __init__(
        self,
        *,
        source_id: str = SOURCE_ID,
        endpoint: str = ENDPOINT,
        directory_endpoint: str = DIRECTORY_ENDPOINT,
        timeout: float = 30,
        max_bytes: int = DEFAULT_MAX_BYTES,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        for label, url in (
            ("country-policy", endpoint),
            ("country-directory", directory_endpoint),
        ):
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"K-SURE {label} endpoint must be HTTPS")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_segment(source_id, "source_id")
        self.source_id = source_id
        self._endpoint = endpoint
        self._directory_endpoint = directory_endpoint
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(endpoint=<redacted>, "
            f"source_id={self.source_id!r})"
        )

    def fetch(self) -> dict[str, Any]:
        payload = {
            "schema_version": "1.0",
            "directory": self._post(self._directory_endpoint, {}),
            "policy_filters": {
                "normal": self._post(
                    self._endpoint,
                    {"insuChkFlag1": "T", "mapTabFlag": "tab"},
                ),
                "conditional": self._post(
                    self._endpoint,
                    {"jogunRiskFlag": "T", "mapTabFlag": "tab"},
                ),
                "restricted": self._post(
                    self._endpoint,
                    {"highRishFlag1": "T", "mapTabFlag": "tab"},
                ),
                "deep_watch": self._post(
                    self._endpoint,
                    {"depWatchFlag1": "T", "mapTabFlag": "tab"},
                ),
            },
        }
        try:
            parse_ksure_country_policy_payload(payload)
        except ValueError as exc:
            raise KsureCountryPolicyError(str(exc)) from None
        return payload

    def _post(self, endpoint: str, document: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(document, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Referer": REFERER,
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise KsureCountryPolicyError(
                f"K-SURE country policy returned HTTP {exc.code}"
            ) from None
        except urllib.error.URLError:
            raise KsureCountryPolicyError(
                "K-SURE country policy is unreachable"
            ) from None
        if len(raw) > self._max_bytes:
            raise KsureCountryPolicyError(
                "K-SURE country-policy response exceeds the size limit"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KsureCountryPolicyError(
                "K-SURE country policy did not return valid UTF-8 JSON"
            ) from None
        if not isinstance(payload, dict):
            raise KsureCountryPolicyError(
                "K-SURE country policy response must be a JSON object"
            )
        return payload

    def collect(
        self,
        root: Path | str,
        *,
        retrieved_at: datetime | None = None,
    ) -> Path:
        payload = self.fetch()
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
