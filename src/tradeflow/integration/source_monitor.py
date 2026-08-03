"""Fetch official knowledge sources without silently retaining their content."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.request import Request, urlopen


_WHITESPACE = re.compile(r"\s+")
_MAX_RESPONSE_BYTES = 5_000_000


@dataclass(frozen=True)
class SourceMonitorSpec:
    source_id: str
    url: str
    required_markers: tuple[str, ...]
    storage_policy: str


@dataclass(frozen=True)
class SourceMonitorResult:
    source_id: str
    checked_at: datetime
    status: str
    http_status: int
    final_url: str
    content_type: str
    content_length: int
    response_sha256: str
    missing_markers: tuple[str, ...]
    storage_policy: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "checked_at": self.checked_at.isoformat(),
            "status": self.status,
            "http_status": self.http_status,
            "final_url": self.final_url,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "response_sha256": self.response_sha256,
            "missing_markers": list(self.missing_markers),
            "storage_policy": self.storage_policy,
            "error": self.error,
        }


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        return _normalize(" ".join(self.parts))


def parse_monitor_specs(payload: dict[str, Any]) -> tuple[SourceMonitorSpec, ...]:
    return tuple(
        SourceMonitorSpec(
            source_id=item["source_id"],
            url=item["url"],
            required_markers=tuple(item["required_markers"]),
            storage_policy=item["storage_policy"],
        )
        for item in payload["monitors"]
    )


def fetch_and_check(
    spec: SourceMonitorSpec,
    *,
    opener: Callable[..., Any] = urlopen,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SourceMonitorResult:
    request = Request(
        spec.url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "KB Comme-Knowledge-Monitor/0.1",
        },
    )
    with opener(request, timeout=30) as response:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError(
                f"{spec.source_id}: response exceeds {_MAX_RESPONSE_BYTES} bytes"
            )
        charset = response.headers.get_content_charset() or "utf-8"
        content = body.decode(charset, errors="replace")
        visible_text = _visible_text(content)
        missing = tuple(
            marker
            for marker in spec.required_markers
            if _normalize(marker) not in visible_text
        )
        http_status = int(response.getcode())
        return SourceMonitorResult(
            source_id=spec.source_id,
            checked_at=now(),
            status="changed_or_unavailable" if missing else "verified",
            http_status=http_status,
            final_url=response.geturl(),
            content_type=response.headers.get("Content-Type", ""),
            content_length=len(body),
            response_sha256=(
                "sha256:" + hashlib.sha256(body).hexdigest()
            ),
            missing_markers=missing,
            storage_policy=spec.storage_policy,
        )


def check_all(
    specs: tuple[SourceMonitorSpec, ...],
    *,
    opener: Callable[..., Any] = urlopen,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[SourceMonitorResult, ...]:
    """Check every source, isolating the ones that cannot be reached.

    A single unreachable host must not decide the freshness of the other
    sources. Letting one network failure abort the run would leave every rule
    fail-closed over an unrelated server. An unreachable source is recorded as
    `unreachable`, which downstream reads as "not verified" — never as
    "verified".
    """
    results: list[SourceMonitorResult] = []
    for spec in specs:
        try:
            results.append(fetch_and_check(spec, opener=opener, now=now))
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            results.append(
                SourceMonitorResult(
                    source_id=spec.source_id,
                    checked_at=now(),
                    status="unreachable",
                    http_status=0,
                    final_url=spec.url,
                    content_type="",
                    content_length=0,
                    response_sha256="",
                    missing_markers=(),
                    storage_policy=spec.storage_policy,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return tuple(results)


def verification_payload(results: tuple[SourceMonitorResult, ...]) -> dict[str, Any]:
    """The snapshot body: one verdict per source, and nothing from the page.

    `storage_policy` in the manifest forbids retaining response bodies until
    each source's redistribution terms are checked, so only the fingerprint and
    the marker verdict are kept.
    """
    return {
        "schema_version": "1.0",
        "results": [item.as_dict() for item in results],
    }


def report_json(results: tuple[SourceMonitorResult, ...]) -> str:
    return json.dumps(
        verification_payload(results),
        ensure_ascii=False,
        indent=2,
    )


def _visible_text(content: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(content)
    return parser.text()


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()
