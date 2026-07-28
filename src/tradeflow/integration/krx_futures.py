"""KRX daily USD futures benchmark adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar

from tradeflow.domain.datasets import (
    DatasetContractError,
    parse_listed_fx_futures_daily_payload,
)
from tradeflow.domain.snapshot import require_aware
from tradeflow.domain.snapshot_file import safe_segment
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot


ENDPOINT = "https://data-dbg.krx.co.kr/svc/apis/drv/fut_bydd_trd"
SAMPLE_ENDPOINT = "https://data-dbg.krx.co.kr/svc/sample/apis/drv/fut_bydd_trd"
SOURCE_ID = "KRX_USD_FUTURES_DAILY"
API_KEY_ENV = "KRX_OPEN_API_KEY"
KST = timezone(timedelta(hours=9))
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


class KrxFuturesError(RuntimeError):
    """Safe-to-report KRX transport or data contract failure."""


def _nullable_decimal(value: Any) -> str | None:
    text = str(value or "").replace(",", "").strip()
    return text if text and text != "-" else None


class KrxUsdFuturesAdapter:
    adapter_key: ClassVar[str] = "krx_usd_futures"

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
        if parsed.scheme != "https" or parsed.netloc != "data-dbg.krx.co.kr":
            raise ValueError("KRX endpoint must be official HTTPS")
        safe_segment(source_id, "source_id")
        self.source_id = source_id
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._opener = opener

    def __repr__(self) -> str:
        return f"{type(self).__name__}(endpoint=<official>, source_id={self.source_id!r})"

    def fetch_raw(self, trading_date: date) -> dict[str, Any]:
        key = self._api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise KrxFuturesError(f"{API_KEY_ENV} is not set")
        query = urllib.parse.urlencode({"basDd": trading_date.strftime("%Y%m%d")})
        request = urllib.request.Request(
            f"{self._endpoint}?{query}",
            headers={"Accept": "application/json", "AUTH_KEY": key},
            method="GET",
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise KrxFuturesError(f"KRX returned HTTP {exc.code}") from None
        except urllib.error.URLError:
            raise KrxFuturesError("KRX is unreachable") from None
        if len(raw) > self._max_bytes:
            raise KrxFuturesError("KRX response exceeds the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise KrxFuturesError("KRX returned invalid UTF-8 JSON") from None
        if not isinstance(payload, dict) or not isinstance(
            payload.get("OutBlock_1"), list
        ):
            raise KrxFuturesError("KRX response omitted OutBlock_1")
        return payload

    def fetch(self, trading_date: date) -> dict[str, Any]:
        raw = self.fetch_raw(trading_date)
        usd_rows = [
            row
            for row in raw["OutBlock_1"]
            if isinstance(row, dict)
            and "미국달러선물"
            in str(row.get("PROD_NM", "")).replace(" ", "")
        ]
        if not usd_rows:
            raise KrxFuturesError(
                "KRX returned no USD futures; verify date and API entitlement"
            )
        observed = datetime.combine(trading_date, datetime.min.time(), tzinfo=KST)
        records = []
        for row in usd_rows:
            try:
                volume = int(str(row.get("ACC_TRDVOL", "0")).replace(",", "") or "0")
                open_interest = int(
                    str(row.get("ACC_OPNINT_QTY", "0")).replace(",", "") or "0"
                )
            except ValueError:
                raise KrxFuturesError("KRX quantities are invalid") from None
            records.append(
                {
                    "instrument_code": str(row.get("ISU_CD", "")).strip(),
                    "instrument_name": str(row.get("ISU_NM", "")).strip(),
                    "product_name": str(row.get("PROD_NM", "")).strip(),
                    "market_name": str(row.get("MKT_NM", "")).strip(),
                    "trading_date": trading_date.isoformat(),
                    "close_price": _nullable_decimal(row.get("TDD_CLSPRC")),
                    "settlement_price": _nullable_decimal(row.get("SETL_PRC")),
                    "spot_price": _nullable_decimal(row.get("SPOT_PRC")),
                    "volume": volume,
                    "open_interest": open_interest,
                }
            )
        payload = {
            "schema_version": "1.0",
            "dataset_id": f"krx-usd-futures-{trading_date.isoformat()}",
            "venue": "KRX",
            "benchmark_class": "listed_fx_future",
            "observed_at": observed.isoformat(),
            "records": records,
        }
        try:
            parse_listed_fx_futures_daily_payload(payload)
        except DatasetContractError as exc:
            raise KrxFuturesError(str(exc)) from None
        return payload

    def collect(
        self,
        root: Path | str,
        *,
        trading_date: date,
        retrieved_at: datetime | None = None,
    ) -> Path:
        payload = self.fetch(trading_date)
        observed = datetime.fromisoformat(payload["observed_at"])
        retrieved = require_aware(
            retrieved_at or datetime.now(timezone.utc), "retrieved_at"
        )
        return write_snapshot(
            root,
            build_envelope(
                source_id=self.source_id,
                version=payload["dataset_id"],
                observed_at=observed,
                retrieved_at=retrieved,
                payload=payload,
            ),
        )
