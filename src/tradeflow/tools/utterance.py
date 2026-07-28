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
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

# Verbs and nouns that betray which way the money moves.
_EXPORT_HINTS = ("수출", "받기로", "받아", "받을", "들어와", "들어올", "입금", "수취")
_IMPORT_HINTS = ("수입", "지급", "나가", "나갈", "결제해", "보내기로", "송금")

_UNIT_SCALE = {"": 1, "천": 1_000, "만": 10_000, "억": 100_000_000}

# A figure only counts as money when a currency marker is attached to it.
# Scanning a window around the digits instead would let the "$" of a later
# token claim an earlier number — "2026-10-24에 $100,000" read as 10.
_AMOUNT_PREFIXED = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(억|만|천)?")
_AMOUNT_SUFFIXED = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(억|만|천)?\s*(?:달러|불|usd|USD)"
)

_YMD = re.compile(r"(\d{4})\s*[-/.년]\s*(\d{1,2})\s*[-/.월]\s*(\d{1,2})")
_MD = re.compile(r"(\d{1,2})\s*[/.월]\s*(\d{1,2})")
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


def _amount(text: str) -> Decimal | None:
    """The figure that is actually a sum of money, not a date or a ratio."""
    for pattern in (_AMOUNT_PREFIXED, _AMOUNT_SUFFIXED):
        for match in pattern.finditer(text):
            digits, scale = match.group(1), match.group(2) or ""
            try:
                value = Decimal(digits.replace(",", "")) * _UNIT_SCALE[scale]
            except (ValueError, ArithmeticError):
                continue
            if value > 0:
                return value
    return None


def _payment_date(text: str, *, as_of: date) -> date | None:
    """A settlement date, with a missing year read as the next occurrence."""
    ymd = _YMD.search(text)
    if ymd:
        try:
            return date(int(ymd.group(1)), int(ymd.group(2)), int(ymd.group(3)))
        except ValueError:
            return None

    md = _MD.search(text)
    if md:
        month, day = int(md.group(1)), int(md.group(2))
        return _next_occurrence(month, day, as_of)

    month_only = _MONTH_ONLY.search(text)
    if month_only:
        # A month with no day is not a settlement date; the agent asks.
        return None
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
