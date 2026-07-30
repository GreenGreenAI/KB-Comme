"""Reading trade slots out of a sentence someone typed.

The intake agent needs something to hand the slot validator when the user
writes prose instead of filling a form. This does that extraction with rules,
not a model: a misread amount would become a wrong exposure, and the failure
would be silent. Anything the patterns do not clearly match is left out, and
the agent asks for it (§4.2[1]).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

# Verbs and nouns that betray which way the money moves.
_EXPORT_HINTS = ("수출", "받기로", "받아", "받을", "들어와", "들어올", "입금", "수취")
_IMPORT_HINTS = ("수입", "지급", "나가", "나갈", "결제해", "보내기로", "송금")

_UNIT_SCALE = {
    "": 1,
    "천": 1_000,
    "만": 10_000,
    "십만": 100_000,
    "백만": 1_000_000,
    "천만": 10_000_000,
    "억": 100_000_000,
    "조": 1_000_000_000_000,
}

#: A magnitude written the way people write them, compound forms included.
#: `1천만 달러` is an ordinary way to write ten million dollars and it was not
#: read at all — the pattern took one scale token, so `1` + `천` matched and
#: then `만 달러` did not follow. Longest alternatives first: regex alternation
#: takes the first that matches, and `만` before `천만` would eat the tail.
_SCALES = "억|조|천만|백만|십만|만|천"

# A figure only counts as money when a currency marker is attached to it.
# Scanning a window around the digits instead would let the "$" of a later
# token claim an earlier number — "2026-10-24에 $100,000" read as 10.
#: One or more `digits + magnitude` groups, so `1억 5천만` is summed rather
#: than read as its first part. Under-reading is worse than not reading: the
#: figure would look heard and be wrong.
_PARTS = rf"(?:\d[\d,]*(?:\.\d+)?\s*(?:{_SCALES})?\s*)+"
_PART = re.compile(rf"(\d[\d,]*(?:\.\d+)?)\s*({_SCALES})?")

_AMOUNT_PREFIXED = re.compile(rf"\$\s*({_PARTS})")
_AMOUNT_SUFFIXED = re.compile(rf"({_PARTS})\s*(?:달러|불|usd|USD)")

#: A sum in won. Not an exposure amount — §5.1 measures foreign currency, and
#: a contract denominated in KRW carries none. But hearing it matters: a
#: company that said "3억 원 규모" and was asked "거래 금액이 얼마인가요?" reads
#: that as not having been heard, and the "(달러 기준)" in the question looks
#: like its problem rather than ours.
_KRW_AMOUNT = re.compile(rf"({_PARTS})\s*원")

#: Counterparty countries by the names a Korean exporter writes. Partial and
#: openly so — the trading partners this product was designed against, not a
#: world list. An unlisted country is not read, which leaves it a question.
_COUNTRIES = {
    "베트남": "VN", "중국": "CN", "미국": "US", "일본": "JP",
    "독일": "DE", "브라질": "BR", "인도": "IN", "인도네시아": "ID",
    "태국": "TH", "말레이시아": "MY", "싱가포르": "SG", "필리핀": "PH",
    "멕시코": "MX", "튀르키예": "TR", "터키": "TR", "폴란드": "PL",
    "호주": "AU", "캐나다": "CA", "영국": "GB", "프랑스": "FR",
    "이탈리아": "IT", "스페인": "ES", "네덜란드": "NL", "러시아": "RU",
    "사우디": "SA", "아랍에미리트": "AE", "대만": "TW", "홍콩": "HK",
}

_YMD = re.compile(r"(\d{4})\s*[-/.년]\s*(\d{1,2})\s*[-/.월]\s*(\d{1,2})")
#: A day must not be the first digits of an amount. `내년 3월 10만 달러` was
#: read as March 10th — the amount was eaten by the date and then reported as
#: understood, which is worse than not reading it at all.
#: `(?!\d)` after the day matters as much as the lookahead after it. Without
#: it the engine backtracks: blocked from taking `10` in `3월 10만`, it takes
#: the `1` instead and reads the first of March.
_MD = re.compile(
    rf"(\d{{1,2}})\s*[/.월]\s*(\d{{1,2}})(?!\d)\s*일?"
    rf"(?!\s*(?:{_SCALES}|달러|불|원|usd|USD))"
)

#: "2달 후", "두 달 뒤", "3개월 후", "45일 뒤", "다음 달". A settlement date
#: stated in relative terms is still stated — asking for it again reads as not
#: having listened, and the reading is shown back as `understood` so a wrong
#: one can be corrected.
_KOREAN_COUNT = {
    "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6,
    "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
}
_RELATIVE_MONTHS = re.compile(
    r"(\d+|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(?:달|개월)\s*(?:후|뒤|이내|안)"
)
_RELATIVE_DAYS = re.compile(r"(\d+)\s*일\s*(?:후|뒤|이내|안)")
_NEXT_MONTH = re.compile(r"다음\s*달")

#: What a date near these words is a date *of*. A sentence carries several
#: dates and they are not interchangeable: "9월 3일에 선적합니다" was read as a
#: settlement date, so the screen reported a payment date nobody had given and
#: called it understood. Mishearing is worse than not hearing — a gap asks a
#: question, a misread produces a whole answer built on the wrong day.
_DATE_ROLE = (
    ("expected_shipment_date", ("선적", "출하", "출고", "船積")),
    ("contract_date", ("계약", "발주", "수주", "체결")),
)

#: The currency a sentence names. §2.4 fixed the MVP to USD and `read_slots`
#: refuses anything else — but only when the currency reaches it. Reading none
#: let a euro trade default to dollars and be analysed as one, which is the
#: refusal being bypassed rather than passed.
#: 보증대상 자금, in the words a company uses for it.
#:
#: The values are the rulepack's own enum — a K-SURE 수출신용보증(선적전) rule
#: already exists and lists them, and it has never once fired because nothing
#: fills `financing.purpose`. The company says "제작에 들어갈 자금이
#: 부족합니다"; the rule wants `trade_finance`; no one joined the two.
#:
#: Read conservatively. Claiming a purpose the company did not state would put
#: them in front of a guarantee they cannot apply for, and the rule's own
#: 사전 상담 condition would not catch it. Only phrases that name the money's
#: job are here — bare 자금 is not one of them.
_FINANCING_PURPOSE = (
    (
        "export_material_import_lc",
        ("수출용 원자재", "원자재 수입", "원자재를 수입"),
    ),
    (
        "trade_finance",
        (
            "제작 자금",
            "제작에 들어갈 자금",
            "제작비",
            "생산 자금",
            "생산에 들어갈 자금",
            "운전자금",
            "무역금융",
            "선적 전 자금",
            "선적전 자금",
            "원자재 구매",
            "자금이 부족",
            "자금 조달",
            "자금을 조달",
        ),
    ),
)


def financing_purpose(text: str | None) -> str | None:
    """What the money is for, when the sentence says so.

    Read on its own rather than into a slot: it is not part of the trade, it is
    what the company wants to do about it, and §5.4's eligibility rules read it
    as a fact with its own evidence.
    """
    if not text:
        return None
    for purpose, words in _FINANCING_PURPOSE:
        if any(word in text for word in words):
            return purpose
    return None


_CURRENCIES = {
    "유로": "EUR", "EUR": "EUR", "eur": "EUR",
    "엔화": "JPY", "엔": "JPY", "JPY": "JPY", "jpy": "JPY",
    "위안": "CNY", "CNY": "CNY", "cny": "CNY",
    "파운드": "GBP", "GBP": "GBP", "gbp": "GBP",
    "달러": "USD", "불": "USD", "USD": "USD", "usd": "USD",
}
_MONTH_ONLY = re.compile(r"(\d{1,2})\s*월(?!\s*\d)")
_ADDITIONAL_TRADE = re.compile(
    r"(?:새\s*거래|추가|별도(?:로)?|(?:^|\s)또(?:\s|$)|"
    r"(?:달러|불|usd)\s*도(?:\s|$))",
    re.IGNORECASE,
)


def _direction(text: str) -> str | None:
    export = next((h for h in _EXPORT_HINTS if h in text), None)
    imports = next((h for h in _IMPORT_HINTS if h in text), None)
    if export and not imports:
        return "수출"
    if imports and not export:
        return "수입"
    if export and imports:
        # Both appear: trust whichever the sentence reaches first.
        return "수출" if text.index(export) < text.index(imports) else "수입"
    return None


def _sum_parts(written: str) -> Decimal | None:
    """`1억 5천만` as one number, or nothing if any part cannot be read."""
    total = Decimal(0)
    for part in _PART.finditer(written):
        digits, scale = part.group(1), part.group(2) or ""
        try:
            total += Decimal(digits.replace(",", "")) * _UNIT_SCALE[scale]
        except (ValueError, ArithmeticError):
            return None
    return total if total > 0 else None


def _amount(text: str) -> Decimal | None:
    """The figure that is actually a sum of money, not a date or a ratio."""
    for pattern in (_AMOUNT_PREFIXED, _AMOUNT_SUFFIXED):
        for match in pattern.finditer(text):
            value = _sum_parts(match.group(1))
            if value is not None:
                return value
    return None


def krw_amount(text: str) -> Decimal | None:
    """A won figure the sentence stated, if any.

    Read separately from `_amount` and never merged into the slots: the
    exposure engine measures foreign currency, so a KRW sum is not the amount
    it needs. It is returned so the screen can say it was heard.
    """
    if not text:
        return None
    for match in _KRW_AMOUNT.finditer(text):
        value = _sum_parts(match.group(1))
        if value is not None:
            return value
    return None


def _currency(text: str) -> str | None:
    """The currency the sentence names, so §2.4's refusal can actually fire."""
    for name, code in _CURRENCIES.items():
        if name in text:
            return code
    return None


def _country(text: str) -> str | None:
    """The counterparty country, when the sentence names one plainly."""
    for name, code in sorted(_COUNTRIES.items(), key=lambda item: len(item[0]), reverse=True):
        if name in text:
            return code
    return None


def _role_of(text: str, start: int, end: int, *, bounds: tuple[int, int]) -> str:
    """Which date this is, read from the words that belong to it.

    Korean puts the qualifier after the date — "9월 3일 선적" — so the text
    that follows decides, and the text between two dates belongs to the earlier
    one. Reading backwards as well let the second date in "9월 3일 선적, 10월
    24일 결제" take the first one's 선적, and the settlement date vanished.

    The words before a date are read only when nothing precedes it, which is
    the one position where "계약일은 7월 1일" cannot be confused with anything.
    """
    tail = text[end : min(bounds[1], end + 18)]
    for role, hints in _DATE_ROLE:
        if any(hint in tail for hint in hints):
            return role
    if bounds[0] == 0:
        lead = text[max(0, start - 16) : start]
        for role, hints in _DATE_ROLE:
            if any(hint in lead for hint in hints):
                return role
    return "expected_payment_date"


def _dates(text: str, *, as_of: date) -> dict[str, date]:
    """Every date the sentence states, under the role it states it in."""
    spans = sorted(
        {(m.start(), m.end()) for p in (_YMD, _MD) for m in p.finditer(text)}
    )

    def bounds(start: int, end: int) -> tuple[int, int]:
        left = max((e for s, e in spans if e <= start), default=0)
        right = min((s for s, e in spans if s >= end), default=len(text))
        return left, right

    found: dict[str, date] = {}
    for match in _YMD.finditer(text):
        try:
            moment = date(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
        except ValueError:
            continue
        role = _role_of(
            text, match.start(), match.end(),
            bounds=bounds(match.start(), match.end()),
        )
        found.setdefault(role, moment)
    for match in _MD.finditer(text):
        role = _role_of(
            text, match.start(), match.end(),
            bounds=bounds(match.start(), match.end()),
        )
        # A contract is signed before today; a settlement and a shipment come
        # after. Reading every bare month-day forward made "7월 1일에
        # 계약했습니다" a contract dated next year.
        resolve = _last_occurrence if role == "contract_date" else _next_occurrence
        moment = resolve(int(match.group(1)), int(match.group(2)), as_of)
        if moment is not None:
            found.setdefault(role, moment)
    return found


def _payment_date(text: str, *, as_of: date) -> date | None:
    """A settlement date, with a missing year read as the next occurrence."""
    stated = _dates(text, as_of=as_of)
    if "expected_payment_date" in stated:
        return stated["expected_payment_date"]

    relative = _relative(text, as_of=as_of)
    if relative is not None:
        return relative

    month_only = _MONTH_ONLY.search(text)
    if month_only:
        # A month with no day is not a settlement date; the agent asks.
        return None
    return None


def _relative(text: str, *, as_of: date) -> date | None:
    """A date the sentence gave in months or days from now."""
    months = _RELATIVE_MONTHS.search(text)
    if months:
        written = months.group(1)
        count = _KOREAN_COUNT.get(written) or int(written) if not written.isdigit() else int(written)
        return _add_months(as_of, count)
    if _NEXT_MONTH.search(text):
        return _add_months(as_of, 1)
    days = _RELATIVE_DAYS.search(text)
    if days:
        return as_of + timedelta(days=int(days.group(1)))
    return None


def _add_months(start: date, months: int) -> date | None:
    """The same day of the month, clamped where that day does not exist.

    31 January plus one month is 28 February, not 3 March. A settlement date
    that rolled into the next month would move the cashflow event to the wrong
    side of a month end.
    """
    if months <= 0:
        return None
    total = start.month - 1 + months
    year, month = start.year + total // 12, total % 12 + 1
    last = monthrange(year, month)[1]
    return date(year, month, min(start.day, last))


def _last_occurrence(month: int, day: int, as_of: date) -> date | None:
    """The most recent time this month and day went by."""
    for year in (as_of.year, as_of.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate <= as_of:
            return candidate
    return None


def _next_occurrence(month: int, day: int, as_of: date) -> date | None:
    for year in (as_of.year, as_of.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= as_of:
            return candidate
    return None


def read_utterance(text: str, *, as_of: date) -> dict[str, Any]:
    """Extract whatever the sentence clearly states, and nothing more."""
    slots: dict[str, Any] = {}
    if not text or not text.strip():
        return slots

    direction = _direction(text)
    if direction:
        slots["direction"] = direction

    amount = _amount(text)
    if amount is not None:
        slots["amount"] = str(amount)

    moment = _payment_date(text, as_of=as_of)
    if moment is not None:
        slots["expected_payment_date"] = moment.isoformat()

    for role, moment in _dates(text, as_of=as_of).items():
        if role != "expected_payment_date":
            slots[role] = moment.isoformat()

    country = _country(text)
    if country:
        slots["country"] = country

    currency = _currency(text)
    if currency:
        slots["currency"] = currency

    return slots


#: Fields that describe *which* trade a sentence is about. A sentence that
#: restates one of these against a different value is not filling a blank.
IDENTIFYING_FIELDS = ("direction", "amount", "expected_payment_date")

MERGE = "merge"
APPEND = "append"
AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Placement:
    """Where a newly heard sentence belongs among the trades already known.

    `conflicts` names the fields that made the decision, so the caller can ask
    a question the user can actually answer instead of "무엇을 말씀하신
    건가요?".
    """

    action: str
    conflicts: tuple[str, ...] = ()


def place_utterance(
    heard: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    utterance: str | None = None,
) -> Placement:
    """Decide whether a sentence adds a trade or completes the current one.

    Merging every sentence into the latest case — the behaviour this replaces —
    silently dropped the second trade of a company that both exports and
    imports, which is the customer this product is for. The sentence was read
    correctly and then discarded, so the user was told it had been understood
    and shown an answer that ignored it.

    The rule:

    - nothing stated, or nothing already known → merge, there is no question
    - the sentence only fills blanks → merge
    - it contradicts an identifying field and the sentence explicitly says
      this is additional → append
    - otherwise a contradiction → ambiguous; it may be a correction

    The last case is left for the user. "12월 3일에 15만 달러 수취" after an
    export of 10만 is either a second shipment or a correction, and the data
    cannot tell which. Guessing "append" invents a trade; guessing "merge"
    destroys one. §1.1 says an agent that cannot decide from its input asks.
    """
    if not heard or not cases:
        return Placement(MERGE)

    target = cases[-1]
    conflicts = tuple(
        field
        for field in IDENTIFYING_FIELDS
        if _stated(heard, field)
        and _stated(target, field)
        and _differs(heard[field], target[field], field)
    )

    explicit_addition = bool(
        utterance and _ADDITIONAL_TRADE.search(utterance)
    )
    if explicit_addition:
        return Placement(APPEND, conflicts)
    if not conflicts:
        return Placement(MERGE)
    return Placement(AMBIGUOUS, conflicts)


def _stated(values: Mapping[str, Any], field: str) -> bool:
    value = values.get(field)
    return value is not None and value != ""


def _differs(heard: Any, known: Any, field: str) -> bool:
    if field == "direction":
        return _direction_value(heard) != _direction_value(known)
    if field == "amount":
        try:
            return Decimal(str(heard)) != Decimal(str(known))
        except (ArithmeticError, ValueError):
            return str(heard) != str(known)
    return str(heard) != str(known)


def _direction_value(value: Any) -> str:
    """Compare directions across the vocabularies that reach this function.

    The extractor returns "수출"/"수입" while a case already read by intake
    carries "export"/"import". Comparing them as plain strings would make every
    second sentence look like a direction change.
    """
    text = str(value).strip().lower()
    if text in {"수출", "export"}:
        return "export"
    if text in {"수입", "import"}:
        return "import"
    return text
