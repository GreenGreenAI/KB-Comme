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
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from tradeflow.domain.datasets import DatasetContractError, parse_trade_feed_payload
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


def parse_trade_feed(payload: Any) -> TradeFeedBatch:
    """Validate version 1 of the normalized feed and create domain values."""
    try:
        data = parse_trade_feed_payload(payload)
    except DatasetContractError as exc:
        raise TradeFeedError(str(exc)) from None
    return TradeFeedBatch(
        version=data.version,
        observed_at=data.observed_at,
        cases=data.cases,
        opening_balances=data.opening_balances,
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
