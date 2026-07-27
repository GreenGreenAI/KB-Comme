"""Collecting the USD/KRW reference rate from the Bank of Korea's ECOS API.

The series this module stores is the input to realized-volatility estimation
(§5.2), so it keeps the response exactly as ECOS returned it and leaves every
interpretation to the reader. The only judgements made here are which moment
the data describes and which version to file it under.

Run as a script to collect:

    python -m tradeflow.integration.ecos 20160101 20260724
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradeflow.integration.snapshot_store import build_envelope, write_snapshot

ECOS_BASE = "https://ecos.bok.or.kr/api"
SOURCE_ID = "ECOS_USD_KRW"

# 3.1.1.1. 주요국 통화의 대원화환율 → 원/미국달러(매매기준율), 일별.
# Confirmed against StatisticTableList / StatisticItemList rather than assumed.
STAT_CODE = "731Y001"
ITEM_CODE = "0000001"
CYCLE = "D"

# ECOS publishes on the Korean business calendar and timestamps by date only.
KST = timezone(timedelta(hours=9))

# One request must return the whole range: a partial series would silently
# shorten the observation window a later volatility estimate is built on.
MAX_ROWS = 100_000

API_KEY_ENV = "ECOS_API_KEY"


class EcosError(RuntimeError):
    """Raised when ECOS cannot serve the requested range.

    Never carries the request URL, which embeds the API key.
    """


def load_api_key(start: Path | str | None = None) -> str:
    """Read the API key from the environment, falling back to a `.env` file.

    The `.env` search walks upward so a git worktree finds the key its main
    checkout holds. The key is never written to a snapshot or an error message.
    """
    key = os.environ.get(API_KEY_ENV)
    if key:
        return key

    current = Path(start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == API_KEY_ENV:
                cleaned = value.strip().strip('"').strip("'")
                if cleaned:
                    return cleaned

    raise EcosError(
        f"{API_KEY_ENV} is not set and no .env above {current} defines it"
    )


def _request(path_parts: tuple[str, ...], api_key: str) -> dict[str, Any]:
    url = f"{ECOS_BASE}/" + "/".join((path_parts[0], api_key, *path_parts[1:]))
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise EcosError(f"ECOS returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise EcosError(f"ECOS is unreachable: {exc.reason}") from None


def fetch_rates(start: str, end: str, *, api_key: str) -> dict[str, Any]:
    """Fetch the daily reference rate for a closed date range (YYYYMMDD).

    Returns the `StatisticSearch` object verbatim.
    """
    document = _request(
        (
            "StatisticSearch",
            "json",
            "kr",
            "1",
            str(MAX_ROWS),
            STAT_CODE,
            CYCLE,
            start,
            end,
            ITEM_CODE,
        ),
        api_key,
    )

    if "RESULT" in document:
        result = document["RESULT"]
        raise EcosError(f"ECOS {result.get('CODE')}: {result.get('MESSAGE')}")

    body = document["StatisticSearch"]
    total = int(body["list_total_count"])
    rows = body["row"]
    if total != len(rows):
        raise EcosError(
            f"ECOS returned {len(rows)} of {total} rows; the range would be "
            "stored incomplete"
        )
    return body


def observed_date(payload: dict[str, Any]) -> date:
    """The most recent business day the payload covers."""
    times = [row["TIME"] for row in payload["row"]]
    if not times:
        raise EcosError("payload contains no observations")
    return datetime.strptime(max(times), "%Y%m%d").date()


def observed_at(payload: dict[str, Any]) -> datetime:
    """Treat a daily observation as the start of its business day, in KST.

    ECOS dates a rate without a time. Placing it at the start of the day makes
    the reading look slightly older than it is, which is the safe direction for
    a freshness check to err in.
    """
    return datetime.combine(observed_date(payload), datetime.min.time(), tzinfo=KST)


def collect(
    root: Path | str,
    start: str,
    end: str,
    *,
    api_key: str | None = None,
    retrieved_at: datetime | None = None,
) -> Path:
    """Fetch a range and file it as a snapshot, returning the written path."""
    payload = fetch_rates(start, end, api_key=api_key or load_api_key())
    moment = observed_at(payload)
    envelope = build_envelope(
        source_id=SOURCE_ID,
        version=moment.date().isoformat(),
        observed_at=moment,
        retrieved_at=retrieved_at or datetime.now(KST),
        payload=payload,
    )
    return write_snapshot(root, envelope)


@dataclass(frozen=True)
class EcosFxAdapter:
    """Official daily USD/KRW reference-rate adapter.

    The class form gives orchestration code a provider-shaped boundary while
    the existing functions remain available for scripts and tests. Credentials
    are resolved only when a request is made and never become snapshot data.
    """

    api_key: str | None = field(default=None, repr=False)
    source_id: str = SOURCE_ID

    def fetch(self, start: str, end: str) -> dict[str, Any]:
        return fetch_rates(start, end, api_key=self.api_key or load_api_key())

    def collect(
        self,
        root: Path | str,
        start: str,
        end: str,
        *,
        retrieved_at: datetime | None = None,
    ) -> Path:
        payload = self.fetch(start, end)
        moment = observed_at(payload)
        envelope = build_envelope(
            source_id=self.source_id,
            version=moment.date().isoformat(),
            observed_at=moment,
            retrieved_at=retrieved_at or datetime.now(KST),
            payload=payload,
        )
        return write_snapshot(root, envelope)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m tradeflow.integration.ecos <YYYYMMDD> <YYYYMMDD>")
        return 2

    root = Path(__file__).resolve().parents[3] / "data" / "snapshots"
    path = collect(root, args[0], args[1])
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
