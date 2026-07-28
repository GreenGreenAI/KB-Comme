"""HTTPS adapter for tenant-private observed forward quote histories."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tradeflow.domain.datasets import (
    DatasetContractError,
    ObservedForwardQuoteDataset,
    parse_observed_forward_quote_payload,
)
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot


DEFAULT_MAX_BYTES = 25 * 1024 * 1024


class ForwardQuoteFeedError(RuntimeError):
    """Safe-to-report acquisition, scope, or contract failure."""


class JsonForwardQuoteHistoryAdapter:
    """Collect connector-normalized quotes without storing credentials.

    ``private_root`` passed to :meth:`collect` must be a tenant-private,
    encrypted-at-rest store in production. The adapter intentionally has no
    default pointing at the repository's public ``data/snapshots`` directory.
    """

    adapter_key = "observed_forward_quote_json"

    def __init__(
        self,
        *,
        endpoint: str,
        source_id: str,
        tenant_id: str,
        bearer_token: str | None = None,
        bearer_token_env: str | None = None,
        timeout: float = 30,
        max_bytes: int = DEFAULT_MAX_BYTES,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise ValueError("forward quote endpoint must be an absolute HTTPS URL")
        if bearer_token is not None and bearer_token_env is not None:
            raise ValueError("configure bearer_token or bearer_token_env, not both")
        if bearer_token_env is not None and not bearer_token_env:
            raise ValueError("bearer_token_env must not be empty")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        safe_segment(source_id, "source_id")
        self._endpoint = endpoint
        self.source_id = source_id
        self.tenant_id = tenant_id.strip()
        self._bearer_token = bearer_token
        self._bearer_token_env = bearer_token_env
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(endpoint=<redacted>, "
            f"source_id={self.source_id!r}, tenant_id=<redacted>)"
        )

    def fetch(self) -> tuple[ObservedForwardQuoteDataset, dict[str, Any]]:
        headers = {"Accept": "application/json"}
        token = self._bearer_token
        if token is None and self._bearer_token_env is not None:
            token = os.environ.get(self._bearer_token_env)
            if not token:
                raise ForwardQuoteFeedError(
                    f"credential environment {self._bearer_token_env} is not set"
                )
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self._endpoint,
            headers=headers,
            method="GET",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ForwardQuoteFeedError(
                f"forward quote feed returned HTTP {exc.code}"
            ) from None
        except urllib.error.URLError:
            raise ForwardQuoteFeedError("forward quote feed is unreachable") from None
        if len(raw) > self._max_bytes:
            raise ForwardQuoteFeedError("forward quote feed exceeds the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ForwardQuoteFeedError(
                "forward quote feed did not return valid UTF-8 JSON"
            ) from None
        try:
            dataset = parse_observed_forward_quote_payload(payload)
        except DatasetContractError as exc:
            raise ForwardQuoteFeedError(str(exc)) from None
        if dataset.tenant_id != self.tenant_id:
            raise ForwardQuoteFeedError("forward quote tenant scope does not match")
        return dataset, payload

    def collect(
        self,
        private_root: Path | str,
        *,
        retrieved_at: datetime | None = None,
    ) -> Path:
        dataset, payload = self.fetch()
        retrieved = require_aware(
            retrieved_at or datetime.now(timezone.utc),
            "retrieved_at",
        )
        if dataset.observed_at > retrieved:
            raise ForwardQuoteFeedError(
                "forward quote observed_at cannot be later than retrieved_at"
            )
        return write_snapshot(
            private_root,
            build_envelope(
                source_id=self.source_id,
                version=dataset.dataset_id,
                observed_at=dataset.observed_at,
                retrieved_at=retrieved,
                payload=payload,
            ),
        )
