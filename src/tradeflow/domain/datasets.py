"""Deterministic readers for versioned runtime datasets.

Network adapters write raw snapshots. This module is the shared, network-free
boundary that validates those snapshots and turns them into domain values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from tradeflow.domain.enums import Freshness, PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef, require_aware
from tradeflow.domain.snapshot_file import read_snapshot, safe_segment

ECOS_USD_KRW_SOURCE_ID = "ECOS_USD_KRW"
ECOS_STAT_CODE = "731Y001"
ECOS_ITEM_CODE = "0000001"


class DatasetContractError(ValueError):
    """A snapshot payload does not satisfy its versioned data contract."""


class StaleDatasetError(RuntimeError):
    """A valid snapshot is too old for the requested operation."""


@dataclass(frozen=True)
class TradeFeedData:
    version: str
    observed_at: datetime
    cases: tuple[TradeCase, ...]
    opening_balances: Mapping[str, Decimal]


@dataclass(frozen=True)
class FxObservation:
    observed_on: date
    rate: Decimal


@dataclass(frozen=True)
class FxSeries:
    base_currency: str
    quote_currency: str
    unit: str
    observations: tuple[FxObservation, ...]

    @property
    def latest(self) -> FxObservation:
        return self.observations[-1]


@dataclass(frozen=True)
class SupportProgram:
    program_id: str
    title: str
    authority: str
    executing_agency: str | None
    category: str
    target: str
    summary: str | None
    application_period: str | None
    url: str
    hashtags: tuple[str, ...]
    published_at: datetime | None


@dataclass(frozen=True)
class SupportProgramCatalog:
    programs: tuple[SupportProgram, ...]
    total_count: int


@dataclass(frozen=True)
class SnapshotDataset:
    ref: SnapshotRef
    value: TradeFeedData | FxSeries | SupportProgramCatalog


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DatasetContractError(f"{field} must be a non-empty string")
    return value.strip()


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise DatasetContractError(f"{field} must be a decimal string or number")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise DatasetContractError(f"{field} is not a valid decimal") from None
    if not result.is_finite():
        raise DatasetContractError(f"{field} must be finite")
    return result


def parse_trade_feed_payload(payload: Any) -> TradeFeedData:
    """Validate version 1 of the normalized enterprise trade feed."""
    if not isinstance(payload, dict):
        raise DatasetContractError("feed root must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version != "1.0":
        raise DatasetContractError(
            f"unsupported schema_version: {schema_version!r}"
        )

    version = _required_text(payload, "version")
    try:
        safe_segment(version, "version")
    except ValueError as exc:
        raise DatasetContractError(str(exc)) from None

    observed_text = _required_text(payload, "observed_at")
    try:
        observed_at = require_aware(
            datetime.fromisoformat(observed_text.replace("Z", "+00:00")),
            "observed_at",
        )
    except ValueError as exc:
        raise DatasetContractError(f"invalid observed_at: {exc}") from None

    records = payload.get("trades")
    if not isinstance(records, list) or not records:
        raise DatasetContractError("trades must be a non-empty array")

    cases: list[TradeCase] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"trades[{index}]"
        if not isinstance(record, dict):
            raise DatasetContractError(f"{prefix} must be an object")
        case_id = _required_text(record, "case_id")
        if case_id in seen:
            raise DatasetContractError(f"duplicate case_id: {case_id}")
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
            raise DatasetContractError(
                f"{prefix} has an invalid enum or date: {exc}"
            ) from None

        confirmed = record.get("confirmed", True)
        if not isinstance(confirmed, bool):
            raise DatasetContractError(f"{prefix}.confirmed must be boolean")
        attributes = record.get("attributes", {})
        if not isinstance(attributes, dict):
            raise DatasetContractError(f"{prefix}.attributes must be an object")
        country = record.get("counterparty_country")
        if country is not None and not isinstance(country, str):
            raise DatasetContractError(
                f"{prefix}.counterparty_country must be a string"
            )
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
            raise DatasetContractError(f"{prefix} is invalid: {exc}") from None

    raw_balances = payload.get("opening_balances", {})
    if not isinstance(raw_balances, dict):
        raise DatasetContractError("opening_balances must be an object")
    balances = {
        _required_text({"currency": currency}, "currency").upper(): _decimal(
            value, f"opening_balances.{currency}"
        )
        for currency, value in raw_balances.items()
    }
    return TradeFeedData(
        version=version,
        observed_at=observed_at,
        cases=tuple(cases),
        opening_balances=balances,
    )


def parse_ecos_usd_krw_payload(payload: Any) -> FxSeries:
    """Validate and normalize the exact ECOS series used by TradeFlow."""
    if not isinstance(payload, dict):
        raise DatasetContractError("ECOS payload must be a JSON object")
    rows = payload.get("row")
    if not isinstance(rows, list) or not rows:
        raise DatasetContractError("ECOS row must be a non-empty array")
    try:
        total = int(payload["list_total_count"])
    except (KeyError, TypeError, ValueError):
        raise DatasetContractError("ECOS list_total_count is invalid") from None
    if total != len(rows):
        raise DatasetContractError(
            f"ECOS payload is partial: {len(rows)} of {total} rows"
        )

    observations: list[FxObservation] = []
    seen_dates: set[date] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise DatasetContractError(f"ECOS row[{index}] must be an object")
        if row.get("STAT_CODE") != ECOS_STAT_CODE:
            raise DatasetContractError(f"ECOS row[{index}] has the wrong STAT_CODE")
        if row.get("ITEM_CODE1") != ECOS_ITEM_CODE:
            raise DatasetContractError(f"ECOS row[{index}] has the wrong ITEM_CODE1")
        if row.get("UNIT_NAME") != "원":
            raise DatasetContractError(f"ECOS row[{index}] has the wrong unit")
        try:
            observed_on = datetime.strptime(
                _required_text(row, "TIME"), "%Y%m%d"
            ).date()
        except ValueError as exc:
            raise DatasetContractError(
                f"ECOS row[{index}] has an invalid date: {exc}"
            ) from None
        if observed_on in seen_dates:
            raise DatasetContractError(f"duplicate ECOS date: {observed_on}")
        seen_dates.add(observed_on)
        rate = _decimal(row.get("DATA_VALUE"), f"ECOS row[{index}].DATA_VALUE")
        if rate <= 0:
            raise DatasetContractError(f"ECOS row[{index}] rate must be positive")
        observations.append(FxObservation(observed_on, rate))

    observations.sort(key=lambda item: item.observed_on)
    return FxSeries(
        base_currency="USD",
        quote_currency="KRW",
        unit="KRW per USD",
        observations=tuple(observations),
    )


def parse_bizinfo_support_payload(payload: Any) -> SupportProgramCatalog:
    """Validate and normalize the official Bizinfo JSON response."""
    if not isinstance(payload, dict):
        raise DatasetContractError("Bizinfo payload must be a JSON object")
    root = payload.get("jsonArray")
    if not isinstance(root, dict):
        raise DatasetContractError("Bizinfo jsonArray must be an object")
    records = root.get("item")
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise DatasetContractError("Bizinfo item must be an array")

    programs: list[SupportProgram] = []
    seen: set[str] = set()
    totals: list[int] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DatasetContractError(f"Bizinfo item[{index}] must be an object")
        program_id = _first_text(record, "pblancId", "seq")
        if program_id in seen:
            raise DatasetContractError(f"duplicate Bizinfo program_id: {program_id}")
        seen.add(program_id)
        total_text = _optional_text(record, "totCnt")
        if total_text is not None:
            try:
                totals.append(int(total_text))
            except ValueError:
                raise DatasetContractError("Bizinfo totCnt must be an integer") from None
        hashtags = tuple(
            item.strip()
            for item in (_optional_text(record, "hashTags") or "").split(",")
            if item.strip()
        )
        programs.append(
            SupportProgram(
                program_id=program_id,
                title=_first_text(record, "pblancNm", "title"),
                authority=_first_text(record, "jrsdInsttNm", "author"),
                executing_agency=_optional_first_text(
                    record, "excInsttNm"
                ),
                category=_first_text(
                    record, "pldirSportRealmLclasCodeNm", "lcategory"
                ),
                target=_first_text(record, "trgetNm"),
                summary=_optional_first_text(record, "bsnsSumryCn", "description"),
                application_period=_optional_first_text(
                    record, "reqstBeginEndDe", "reqstDt"
                ),
                url=_first_text(record, "pblancUrl", "link"),
                hashtags=hashtags,
                published_at=_optional_datetime(
                    _optional_first_text(record, "creatPnttm", "pubDate")
                ),
            )
        )
    total_count = max(totals, default=len(programs))
    if total_count < len(programs):
        raise DatasetContractError("Bizinfo total_count is smaller than item count")
    return SupportProgramCatalog(tuple(programs), total_count)


def _optional_text(record: Mapping[str, Any], field: str) -> str | None:
    value = record.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int)):
        raise DatasetContractError(f"{field} must be text")
    text = str(value).strip()
    return text or None


def _optional_first_text(record: Mapping[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = _optional_text(record, field)
        if value is not None:
            return value
    return None


def _first_text(record: Mapping[str, Any], *fields: str) -> str:
    value = _optional_first_text(record, *fields)
    if value is None:
        raise DatasetContractError(
            "one of these fields is required: " + ", ".join(fields)
        )
    return value


def _optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise DatasetContractError(f"invalid Bizinfo publication date: {value}")


def _require_fresh(
    ref: SnapshotRef,
    policy: FreshnessPolicy,
    evaluated_at: datetime,
) -> None:
    if policy.evaluate(ref, require_aware(evaluated_at, "evaluated_at")) is Freshness.STALE:
        raise StaleDatasetError(
            f"{ref.source_id}@{ref.version} is stale at {evaluated_at.isoformat()}"
        )


def read_trade_feed_snapshot(
    path: Path | str,
    *,
    freshness_policy: FreshnessPolicy,
    evaluated_at: datetime,
) -> SnapshotDataset:
    ref, payload = read_snapshot(path)
    _require_fresh(ref, freshness_policy, evaluated_at)
    data = parse_trade_feed_payload(payload)
    if data.version != ref.version:
        raise DatasetContractError(
            f"feed version {data.version!r} does not match snapshot {ref.version!r}"
        )
    if data.observed_at != ref.observed_at:
        raise DatasetContractError(
            "feed observed_at does not match snapshot observed_at"
        )
    return SnapshotDataset(ref, data)


def read_ecos_usd_krw_snapshot(
    path: Path | str,
    *,
    freshness_policy: FreshnessPolicy,
    evaluated_at: datetime,
) -> SnapshotDataset:
    ref, payload = read_snapshot(path)
    if ref.source_id != ECOS_USD_KRW_SOURCE_ID:
        raise DatasetContractError(
            f"expected {ECOS_USD_KRW_SOURCE_ID}, got {ref.source_id}"
        )
    _require_fresh(ref, freshness_policy, evaluated_at)
    series = parse_ecos_usd_krw_payload(payload)
    if series.latest.observed_on != ref.observed_at.date():
        raise DatasetContractError(
            "latest ECOS observation does not match snapshot observed_at"
        )
    return SnapshotDataset(ref, series)


def trade_program_from_snapshot(
    dataset: SnapshotDataset,
    *,
    program_id: str,
    company: CompanyProfile,
    as_of: date,
) -> TradeProgram:
    if not isinstance(dataset.value, TradeFeedData):
        raise TypeError("dataset is not a trade feed")
    return TradeProgram(
        program_id=program_id,
        company=company,
        cases=dataset.value.cases,
        opening_balances=dict(dataset.value.opening_balances),
        as_of=as_of,
        input_snapshots=(dataset.ref,),
    )
