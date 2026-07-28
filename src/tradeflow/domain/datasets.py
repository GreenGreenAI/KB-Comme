"""Deterministic readers for versioned runtime datasets.

Network adapters write raw snapshots. This module is the shared, network-free
boundary that validates those snapshots and turns them into domain values.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from tradeflow.domain.enums import (
    CountryPolicyStatus,
    EvidenceSubjectKind,
    Freshness,
    PaymentMethod,
    TradeDirection,
)
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
class ReferenceFxRate:
    currency_code: str
    currency_unit: int
    raw_currency_unit: str
    currency_name: str
    telegraphic_buying_rate: Decimal
    telegraphic_selling_rate: Decimal
    deal_base_rate: Decimal
    book_price: Decimal
    yearly_exchange_fee_rate: Decimal
    ten_day_exchange_fee_rate: Decimal
    kftc_deal_base_rate: Decimal
    kftc_book_price: Decimal

    @property
    def krw_per_currency_unit(self) -> Decimal:
        return self.deal_base_rate / Decimal(self.currency_unit)


@dataclass(frozen=True)
class ReferenceFxCatalog:
    observed_on: date
    rates: Mapping[str, ReferenceFxRate]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rates", MappingProxyType(dict(self.rates)))

    def get(self, currency_code: str) -> ReferenceFxRate:
        code = currency_code.strip().upper()
        try:
            return self.rates[code]
        except KeyError:
            raise KeyError(f"reference FX rate is unavailable for {code}") from None


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
class KsureCountryPolicy:
    country_code: str
    country_name: str
    status: CountryPolicyStatus
    deep_watch: bool

    @property
    def country_restricted(self) -> bool:
        if self.status is CountryPolicyStatus.UNKNOWN:
            raise DatasetContractError(
                f"K-SURE country policy status is unknown for {self.country_code}"
            )
        return self.status is CountryPolicyStatus.RESTRICTED


@dataclass(frozen=True)
class KsureCountryPolicyCatalog:
    policies: Mapping[str, KsureCountryPolicy]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policies", MappingProxyType(dict(self.policies)))

    def get(self, country_code: str) -> KsureCountryPolicy:
        code = _country_code(country_code, "country_code")
        try:
            return self.policies[code]
        except KeyError:
            raise KeyError(f"K-SURE country policy is unavailable for {code}") from None


@dataclass(frozen=True)
class EligibilityEvidenceDataRecord:
    evidence_id: str
    company_id: str
    subject_kind: EvidenceSubjectKind
    subject_id: str
    valid_until: datetime | None
    facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))


@dataclass(frozen=True)
class EligibilityEvidenceDataset:
    version: str
    observed_at: datetime
    provider_key: str
    records: tuple[EligibilityEvidenceDataRecord, ...]


@dataclass(frozen=True)
class ForwardQuoteSpotRef:
    source_id: str
    version: str
    content_hash: str


@dataclass(frozen=True)
class ObservedForwardQuote:
    record_id: str
    quote_id: str
    provider_id: str
    company_id: str
    case_ids: tuple[str, ...]
    base_currency: str
    counter_currency: str
    side: str
    notional_min: Decimal
    notional_max: Decimal
    contract_rate: Decimal
    cost_rate: Decimal
    settlement_date: date
    observed_at: datetime
    valid_until: datetime
    origin_spot_snapshot: ForwardQuoteSpotRef
    evidence_content_hash: str
    executed: bool | None
    realized_settlement_rate: Decimal | None
    actual_total_cost: Decimal | None


@dataclass(frozen=True)
class ObservedForwardQuoteDataset:
    dataset_id: str
    tenant_id: str
    retention_class: str
    records: tuple[ObservedForwardQuote, ...]

    @property
    def observed_at(self) -> datetime:
        return max(record.observed_at for record in self.records)


@dataclass(frozen=True)
class SnapshotDataset:
    ref: SnapshotRef
    value: (
        TradeFeedData
        | FxSeries
        | ReferenceFxCatalog
        | SupportProgramCatalog
        | KsureCountryPolicyCatalog
        | EligibilityEvidenceDataset
        | ObservedForwardQuoteDataset
    )


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


def _decimal_string(
    value: Any,
    field: str,
    *,
    positive: bool = False,
) -> Decimal:
    if not isinstance(value, str):
        raise DatasetContractError(f"{field} must be a decimal string")
    result = _decimal(value, field)
    if positive and result <= 0:
        raise DatasetContractError(f"{field} must be positive")
    return result


def _aware_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DatasetContractError(f"{field} must be an ISO timestamp")
    try:
        return require_aware(
            datetime.fromisoformat(value.replace("Z", "+00:00")),
            field,
        )
    except ValueError as exc:
        raise DatasetContractError(f"{field} is invalid: {exc}") from None


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


_KOREAEXIM_UNIT = re.compile(r"^([A-Z]{3})(?:\(([1-9][0-9]*)\))?$")
_KOREAEXIM_FIELDS = {
    "result",
    "cur_unit",
    "ttb",
    "tts",
    "deal_bas_r",
    "bkpr",
    "yy_efee_r",
    "ten_dd_efee_r",
    "kftc_bkpr",
    "kftc_deal_bas_r",
    "cur_nm",
}
_KOREAEXIM_ERRORS = {
    2: "DATA code error",
    3: "authentication code error",
    4: "daily request limit exhausted",
}


def parse_koreaexim_reference_fx_payload(payload: Any) -> ReferenceFxCatalog:
    """Parse the official Korea Eximbank AP01 JSON response wrapper."""
    if not isinstance(payload, dict):
        raise DatasetContractError("Korea Eximbank payload must be an object")
    if set(payload) != {"schema_version", "search_date", "response"}:
        raise DatasetContractError(
            "Korea Eximbank payload requires only schema_version, search_date, response"
        )
    if payload.get("schema_version") != "1.0":
        raise DatasetContractError("unsupported Korea Eximbank schema_version")
    try:
        observed_on = datetime.strptime(
            _required_text(payload, "search_date"), "%Y-%m-%d"
        ).date()
    except ValueError as exc:
        raise DatasetContractError(f"invalid Korea Eximbank search_date: {exc}") from None
    response = payload.get("response")
    if not isinstance(response, list) or not response:
        raise DatasetContractError("Korea Eximbank response must be non-empty")

    rates: dict[str, ReferenceFxRate] = {}
    for index, record in enumerate(response):
        prefix = f"Korea Eximbank response[{index}]"
        if not isinstance(record, Mapping):
            raise DatasetContractError(f"{prefix} must be an object")
        unknown = set(record) - _KOREAEXIM_FIELDS
        missing = _KOREAEXIM_FIELDS - set(record)
        if unknown or missing:
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if unknown:
                details.append("unknown " + ", ".join(sorted(unknown)))
            raise DatasetContractError(f"{prefix} fields invalid: {'; '.join(details)}")
        result = record.get("result")
        if isinstance(result, bool) or not isinstance(result, int):
            raise DatasetContractError(f"{prefix}.result must be an integer")
        if result != 1:
            reason = _KOREAEXIM_ERRORS.get(result, f"unknown result code {result}")
            raise DatasetContractError(f"Korea Eximbank API failed: {reason}")
        raw_unit = _required_text(record, "cur_unit").upper()
        match = _KOREAEXIM_UNIT.fullmatch(raw_unit)
        if match is None:
            raise DatasetContractError(f"{prefix}.cur_unit is invalid: {raw_unit}")
        currency_code = match.group(1)
        currency_unit = int(match.group(2) or "1")
        if currency_code in rates:
            raise DatasetContractError(
                f"duplicate Korea Eximbank currency: {currency_code}"
            )
        values = {
            field: _koreaexim_decimal(record.get(field), f"{prefix}.{field}")
            for field in (
                "ttb",
                "tts",
                "deal_bas_r",
                "bkpr",
                "yy_efee_r",
                "ten_dd_efee_r",
                "kftc_bkpr",
                "kftc_deal_bas_r",
            )
        }
        if values["deal_bas_r"] <= 0:
            raise DatasetContractError(f"{prefix}.deal_bas_r must be positive")
        if any(value < 0 for value in values.values()):
            raise DatasetContractError(f"{prefix} rates must not be negative")
        rates[currency_code] = ReferenceFxRate(
            currency_code=currency_code,
            currency_unit=currency_unit,
            raw_currency_unit=raw_unit,
            currency_name=_required_text(record, "cur_nm"),
            telegraphic_buying_rate=values["ttb"],
            telegraphic_selling_rate=values["tts"],
            deal_base_rate=values["deal_bas_r"],
            book_price=values["bkpr"],
            yearly_exchange_fee_rate=values["yy_efee_r"],
            ten_day_exchange_fee_rate=values["ten_dd_efee_r"],
            kftc_deal_base_rate=values["kftc_deal_bas_r"],
            kftc_book_price=values["kftc_bkpr"],
        )
    return ReferenceFxCatalog(observed_on=observed_on, rates=rates)


def _koreaexim_decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise DatasetContractError(f"{field} must be a decimal string")
    text = value.strip().replace(",", "")
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise DatasetContractError(f"{field} is not a valid decimal") from None
    if not result.is_finite():
        raise DatasetContractError(f"{field} must be finite")
    return result


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


def parse_ksure_country_policy_payload(payload: Any) -> KsureCountryPolicyCatalog:
    """Normalize the current K-Sight country-risk-map policy response."""
    if not isinstance(payload, dict):
        raise DatasetContractError("K-SURE country policy payload must be an object")
    if payload.get("schema_version") != "1.0":
        raise DatasetContractError(
            "unsupported K-SURE country-policy schema_version"
        )
    directory = payload.get("directory")
    filters = payload.get("policy_filters")
    if not isinstance(directory, Mapping) or not isinstance(filters, Mapping):
        raise DatasetContractError(
            "K-SURE country policy requires directory and policy_filters"
        )
    directory_records = directory.get("getNationLst")
    if not isinstance(directory_records, list) or not directory_records:
        raise DatasetContractError("K-SURE getNationLst must be a non-empty array")

    names: dict[str, str] = {}
    for index, record in enumerate(directory_records):
        prefix = f"K-SURE country directory[{index}]"
        if not isinstance(record, dict):
            raise DatasetContractError(f"{prefix} must be an object")
        raw_code = record.get("stdInfrmCtryCd")
        if raw_code in {None, ""}:
            continue
        code = _country_code(raw_code, f"{prefix}.stdInfrmCtryCd")
        if code in names:
            raise DatasetContractError(f"duplicate K-SURE country code: {code}")
        names[code] = _required_text(record, "trgtpsnNm")
    if not names:
        raise DatasetContractError(
            "K-SURE country directory has no alpha-2 country codes"
        )

    sets = {
        name: _ksure_filter_codes(filters.get(name), name, set(names))
        for name in ("normal", "conditional", "restricted", "deep_watch")
    }
    if not sets["restricted"]:
        raise DatasetContractError("K-SURE restricted-country filter is empty")

    policies: dict[str, KsureCountryPolicy] = {}
    for code, name in names.items():
        if code in sets["restricted"]:
            status = CountryPolicyStatus.RESTRICTED
        elif code in sets["conditional"]:
            status = CountryPolicyStatus.CONDITIONAL
        elif code in sets["normal"]:
            status = CountryPolicyStatus.NORMAL
        else:
            status = CountryPolicyStatus.UNKNOWN
        policies[code] = KsureCountryPolicy(
            code, name, status, code in sets["deep_watch"]
        )
    return KsureCountryPolicyCatalog(policies)


def parse_eligibility_evidence_payload(payload: Any) -> EligibilityEvidenceDataset:
    """Validate a normalized private company/K-SURE evidence feed."""
    if not isinstance(payload, dict):
        raise DatasetContractError("eligibility evidence payload must be an object")
    if payload.get("schema_version") != "1.0":
        raise DatasetContractError(
            "unsupported eligibility evidence schema_version"
        )
    unknown_root = set(payload) - {
        "schema_version",
        "version",
        "observed_at",
        "provider_key",
        "records",
    }
    if unknown_root:
        raise DatasetContractError(
            "eligibility evidence payload has unknown fields: "
            + ", ".join(sorted(unknown_root))
        )
    version = _required_text(payload, "version")
    provider_key = _required_text(payload, "provider_key")
    try:
        safe_segment(version, "version")
        safe_segment(provider_key, "provider_key")
    except ValueError as exc:
        raise DatasetContractError(str(exc)) from None
    try:
        observed_at = require_aware(
            datetime.fromisoformat(
                _required_text(payload, "observed_at").replace("Z", "+00:00")
            ),
            "observed_at",
        )
    except ValueError as exc:
        raise DatasetContractError(f"invalid observed_at: {exc}") from None

    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise DatasetContractError("eligibility evidence records must be non-empty")
    records: list[EligibilityEvidenceDataRecord] = []
    evidence_ids: set[str] = set()
    for index, item in enumerate(raw_records):
        prefix = f"eligibility evidence records[{index}]"
        if not isinstance(item, Mapping):
            raise DatasetContractError(f"{prefix} must be an object")
        unknown_record = set(item) - {
            "evidence_id",
            "company_id",
            "subject_kind",
            "subject_id",
            "valid_until",
            "facts",
        }
        if unknown_record:
            raise DatasetContractError(
                f"{prefix} has unknown fields: "
                + ", ".join(sorted(unknown_record))
            )
        evidence_id = _required_text(item, "evidence_id")
        if evidence_id in evidence_ids:
            raise DatasetContractError(f"duplicate evidence_id: {evidence_id}")
        evidence_ids.add(evidence_id)
        try:
            subject_kind = EvidenceSubjectKind(
                _required_text(item, "subject_kind")
            )
        except ValueError as exc:
            raise DatasetContractError(
                f"{prefix}.subject_kind is invalid: {exc}"
            ) from None
        subject_id = _required_text(item, "subject_id")
        company_id = _required_text(item, "company_id")
        if (
            subject_kind is EvidenceSubjectKind.COMPANY
            and subject_id != company_id
        ):
            raise DatasetContractError(
                f"{prefix}: company subject_id must equal company_id"
            )
        raw_valid_until = item.get("valid_until")
        valid_until = None
        if raw_valid_until is not None:
            if not isinstance(raw_valid_until, str) or not raw_valid_until:
                raise DatasetContractError(
                    f"{prefix}.valid_until must be an ISO timestamp or null"
                )
            try:
                valid_until = require_aware(
                    datetime.fromisoformat(raw_valid_until.replace("Z", "+00:00")),
                    f"{prefix}.valid_until",
                )
            except ValueError as exc:
                raise DatasetContractError(
                    f"{prefix}.valid_until is invalid: {exc}"
                ) from None
            if valid_until < observed_at:
                raise DatasetContractError(
                    f"{prefix}.valid_until precedes observed_at"
                )
        raw_facts = item.get("facts")
        if not isinstance(raw_facts, Mapping) or not raw_facts:
            raise DatasetContractError(f"{prefix}.facts must be a non-empty object")
        facts: dict[str, Any] = {}
        for field, value in raw_facts.items():
            if not isinstance(field, str) or not field:
                raise DatasetContractError(f"{prefix}.facts has an invalid field")
            if value is None or isinstance(value, (list, dict)):
                raise DatasetContractError(
                    f"{prefix}.facts.{field} must be a non-null JSON scalar"
                )
            facts[field] = value
        records.append(
            EligibilityEvidenceDataRecord(
                evidence_id=evidence_id,
                company_id=company_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                valid_until=valid_until,
                facts=facts,
            )
        )
    return EligibilityEvidenceDataset(
        version=version,
        observed_at=observed_at,
        provider_key=provider_key,
        records=tuple(records),
    )


_FORWARD_QUOTE_ROOT_FIELDS = {
    "schema_version",
    "dataset_id",
    "tenant_id",
    "retention_class",
    "records",
}
_FORWARD_QUOTE_REQUIRED_FIELDS = {
    "record_id",
    "quote_id",
    "provider_id",
    "company_id",
    "case_ids",
    "base_currency",
    "counter_currency",
    "side",
    "notional_min",
    "notional_max",
    "contract_rate",
    "cost_rate",
    "settlement_date",
    "observed_at",
    "valid_until",
    "quote_basis",
    "provider_verified",
    "company_applicable",
    "origin_spot_snapshot",
    "evidence_content_hash",
}
_FORWARD_QUOTE_OPTIONAL_FIELDS = {
    "executed",
    "realized_settlement_rate",
    "actual_total_cost",
}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


def parse_observed_forward_quote_payload(
    payload: Any,
) -> ObservedForwardQuoteDataset:
    """Validate a tenant-private, company-applicable forward quote history."""
    if not isinstance(payload, Mapping):
        raise DatasetContractError("forward quote payload must be a JSON object")
    if payload.get("schema_version") != "1.0":
        raise DatasetContractError("unsupported forward quote schema_version")
    unknown_root = set(payload) - _FORWARD_QUOTE_ROOT_FIELDS
    missing_root = _FORWARD_QUOTE_ROOT_FIELDS - set(payload)
    if unknown_root or missing_root:
        details = []
        if missing_root:
            details.append("missing " + ", ".join(sorted(missing_root)))
        if unknown_root:
            details.append("unknown " + ", ".join(sorted(unknown_root)))
        raise DatasetContractError(
            "forward quote payload fields invalid: " + "; ".join(details)
        )

    dataset_id = _required_text(payload, "dataset_id")
    tenant_id = _required_text(payload, "tenant_id")
    try:
        safe_segment(dataset_id, "dataset_id")
    except ValueError as exc:
        raise DatasetContractError(str(exc)) from None
    if payload.get("retention_class") != "tenant_private_financial":
        raise DatasetContractError(
            "forward quote retention_class must be tenant_private_financial"
        )

    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise DatasetContractError("forward quote records must be non-empty")

    records: list[ObservedForwardQuote] = []
    record_ids: set[str] = set()
    quote_ids: set[str] = set()
    allowed = _FORWARD_QUOTE_REQUIRED_FIELDS | _FORWARD_QUOTE_OPTIONAL_FIELDS
    for index, item in enumerate(raw_records):
        prefix = f"forward quote records[{index}]"
        if not isinstance(item, Mapping):
            raise DatasetContractError(f"{prefix} must be an object")
        unknown = set(item) - allowed
        missing = _FORWARD_QUOTE_REQUIRED_FIELDS - set(item)
        if unknown or missing:
            details = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if unknown:
                details.append("unknown " + ", ".join(sorted(unknown)))
            raise DatasetContractError(
                f"{prefix} fields invalid: " + "; ".join(details)
            )

        record_id = _required_text(item, "record_id")
        quote_id = _required_text(item, "quote_id")
        if record_id in record_ids:
            raise DatasetContractError(f"duplicate forward quote record_id: {record_id}")
        if quote_id in quote_ids:
            raise DatasetContractError(f"duplicate forward quote quote_id: {quote_id}")
        record_ids.add(record_id)
        quote_ids.add(quote_id)

        raw_case_ids = item.get("case_ids")
        if not isinstance(raw_case_ids, list) or not raw_case_ids:
            raise DatasetContractError(f"{prefix}.case_ids must be non-empty")
        case_ids = tuple(
            _required_text({"case_id": value}, "case_id")
            for value in raw_case_ids
        )
        if len(set(case_ids)) != len(case_ids):
            raise DatasetContractError(f"{prefix}.case_ids must be unique")

        base_currency = _required_text(item, "base_currency")
        counter_currency = _required_text(item, "counter_currency")
        if not _CURRENCY.fullmatch(base_currency):
            raise DatasetContractError(f"{prefix}.base_currency must be ISO 4217")
        if not _CURRENCY.fullmatch(counter_currency):
            raise DatasetContractError(f"{prefix}.counter_currency must be ISO 4217")
        if base_currency == counter_currency:
            raise DatasetContractError(f"{prefix} currencies must differ")
        side = _required_text(item, "side")
        if side not in {"buy", "sell"}:
            raise DatasetContractError(f"{prefix}.side must be buy or sell")

        notional_min = _decimal_string(
            item.get("notional_min"),
            f"{prefix}.notional_min",
            positive=True,
        )
        notional_max = _decimal_string(
            item.get("notional_max"),
            f"{prefix}.notional_max",
            positive=True,
        )
        if notional_max < notional_min:
            raise DatasetContractError(
                f"{prefix}.notional_max must not be below notional_min"
            )
        contract_rate = _decimal_string(
            item.get("contract_rate"),
            f"{prefix}.contract_rate",
            positive=True,
        )
        cost_rate = _decimal_string(item.get("cost_rate"), f"{prefix}.cost_rate")

        try:
            settlement_date = date.fromisoformat(
                _required_text(item, "settlement_date")
            )
        except ValueError as exc:
            raise DatasetContractError(
                f"{prefix}.settlement_date is invalid: {exc}"
            ) from None
        observed_at = _aware_datetime(item.get("observed_at"), f"{prefix}.observed_at")
        valid_until = _aware_datetime(item.get("valid_until"), f"{prefix}.valid_until")
        if valid_until <= observed_at:
            raise DatasetContractError(
                f"{prefix}.valid_until must be later than observed_at"
            )
        if settlement_date < observed_at.date():
            raise DatasetContractError(
                f"{prefix}.settlement_date precedes observed_at"
            )

        if item.get("quote_basis") != "observed_forward_quote":
            raise DatasetContractError(
                f"{prefix}.quote_basis must be observed_forward_quote"
            )
        if item.get("provider_verified") is not True:
            raise DatasetContractError(f"{prefix}.provider_verified must be true")
        if item.get("company_applicable") is not True:
            raise DatasetContractError(f"{prefix}.company_applicable must be true")

        raw_spot = item.get("origin_spot_snapshot")
        if not isinstance(raw_spot, Mapping) or set(raw_spot) != {
            "source_id",
            "version",
            "content_hash",
        }:
            raise DatasetContractError(
                f"{prefix}.origin_spot_snapshot fields are invalid"
            )
        spot_source = _required_text(raw_spot, "source_id")
        spot_version = _required_text(raw_spot, "version")
        try:
            safe_segment(spot_source, "source_id")
            safe_segment(spot_version, "version")
        except ValueError as exc:
            raise DatasetContractError(str(exc)) from None
        spot_hash = _required_text(raw_spot, "content_hash")
        evidence_hash = _required_text(item, "evidence_content_hash")
        if not _SHA256.fullmatch(spot_hash):
            raise DatasetContractError(
                f"{prefix}.origin_spot_snapshot.content_hash is invalid"
            )
        if not _SHA256.fullmatch(evidence_hash):
            raise DatasetContractError(
                f"{prefix}.evidence_content_hash is invalid"
            )

        executed = item.get("executed")
        if executed is not None and not isinstance(executed, bool):
            raise DatasetContractError(f"{prefix}.executed must be boolean or null")
        realized = item.get("realized_settlement_rate")
        actual_cost = item.get("actual_total_cost")
        realized_rate = (
            None
            if realized is None
            else _decimal_string(
                realized,
                f"{prefix}.realized_settlement_rate",
                positive=True,
            )
        )
        total_cost = (
            None
            if actual_cost is None
            else _decimal_string(actual_cost, f"{prefix}.actual_total_cost")
        )

        records.append(
            ObservedForwardQuote(
                record_id=record_id,
                quote_id=quote_id,
                provider_id=_required_text(item, "provider_id"),
                company_id=_required_text(item, "company_id"),
                case_ids=case_ids,
                base_currency=base_currency,
                counter_currency=counter_currency,
                side=side,
                notional_min=notional_min,
                notional_max=notional_max,
                contract_rate=contract_rate,
                cost_rate=cost_rate,
                settlement_date=settlement_date,
                observed_at=observed_at,
                valid_until=valid_until,
                origin_spot_snapshot=ForwardQuoteSpotRef(
                    source_id=spot_source,
                    version=spot_version,
                    content_hash=spot_hash,
                ),
                evidence_content_hash=evidence_hash,
                executed=executed,
                realized_settlement_rate=realized_rate,
                actual_total_cost=total_cost,
            )
        )
    return ObservedForwardQuoteDataset(
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        retention_class="tenant_private_financial",
        records=tuple(records),
    )


def _country_code(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DatasetContractError(f"{field} must be a two-letter country code")
    code = value.strip().upper()
    if len(code) != 2 or not code.isalpha() or not code.isascii():
        raise DatasetContractError(f"{field} must be a two-letter country code")
    return code


def _ksure_filter_codes(
    document: Any,
    filter_name: str,
    directory_codes: set[str],
) -> set[str]:
    if not isinstance(document, Mapping):
        raise DatasetContractError(
            f"K-SURE {filter_name} filter response must be an object"
        )
    records = document.get("selectFilterLst")
    if not isinstance(records, list):
        raise DatasetContractError(
            f"K-SURE {filter_name} selectFilterLst must be an array"
        )
    codes: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"K-SURE {filter_name} filter[{index}]"
        if not isinstance(record, dict):
            raise DatasetContractError(f"{prefix} must be an object")
        raw_code = record.get("ggCode")
        if raw_code in {None, ""}:
            continue
        code = _country_code(raw_code, f"{prefix}.ggCode")
        if code not in directory_codes:
            raise DatasetContractError(
                f"K-SURE {filter_name} filter has unknown country: {code}"
            )
        if code in codes:
            raise DatasetContractError(
                f"K-SURE {filter_name} filter duplicates country: {code}"
            )
        codes.add(code)
    return codes


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


def read_observed_forward_quote_snapshot(
    path: Path | str,
    *,
    tenant_id: str,
) -> SnapshotDataset:
    """Read an immutable private quote snapshot and enforce tenant ownership."""
    ref, payload = read_snapshot(path)
    data = parse_observed_forward_quote_payload(payload)
    if data.dataset_id != ref.version:
        raise DatasetContractError(
            f"forward quote dataset {data.dataset_id!r} does not match "
            f"snapshot {ref.version!r}"
        )
    if data.observed_at != ref.observed_at:
        raise DatasetContractError(
            "forward quote observed_at does not match snapshot observed_at"
        )
    if data.tenant_id != tenant_id:
        raise DatasetContractError("forward quote tenant scope does not match")
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
