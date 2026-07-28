"""Validating trade-case slots and deciding what still has to be asked.

This is the intake agent's paired tool (§4.2[1]). The agent decides how to word
a question; whether a question is needed at all is decided here, deterministically.

The target user does not know their own exposure, so most sessions start
incomplete. Asking for everything at once loses them — §4.2 caps a turn at three
questions and names the three that make an exposure calculation possible, so the
rest can be gathered after the first answer is on screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

# §2.4 fixed the MVP to a single currency and a single payment method, so these
# two slots are answered before the user is asked anything.
MVP_DEFAULTS: dict[str, str] = {"currency": "USD", "payment_method": "TT"}

REQUIRED_SLOTS = ("direction", "amount", "expected_payment_date")
OPTIONAL_SLOTS = (
    "country",
    "counterparty_id",
    "expected_shipment_date",
    "advance_payment_ratio",
    "contract_date",
)

# Exposure can be computed from these three alone. Everything else improves the
# answer rather than enabling it (§4.2 되묻기 정책).
ASK_ORDER = ("amount", "expected_payment_date", "direction")
MAX_QUESTIONS_PER_TURN = 3

_DIRECTIONS = {
    "export": "export",
    "수출": "export",
    "import": "import",
    "수입": "import",
}

_QUESTIONS = {
    "amount": "거래 금액이 얼마인가요? (달러 기준)",
    "expected_payment_date": "대금을 주고받기로 한 날짜가 언제인가요?",
    "direction": "수출 건인가요, 수입 건인가요?",
}


@dataclass(frozen=True)
class SlotIssue:
    """One slot that could not be accepted, and why."""

    field: str
    reason: str


@dataclass(frozen=True)
class SlotReading:
    """What was understood, what is missing, and what to ask next."""

    values: dict[str, Any]
    missing: tuple[str, ...]
    issues: tuple[SlotIssue, ...]

    @property
    def complete(self) -> bool:
        return not self.missing and not self.issues

    def prompts(self) -> tuple[tuple[str, str], ...]:
        """The next slots to ask about, each with its question.

        Field and wording travel together so a caller cannot pair the wrong
        two. `missing` is in schema order while asking follows ASK_ORDER, and a
        screen that read `missing[0]` for the field but `questions[0]` for the
        wording offered a direction chooser under a question about the date.
        """
        pending = [slot for slot in ASK_ORDER if slot in self.missing]
        pending += [slot for slot in self.missing if slot not in ASK_ORDER]
        return tuple(
            (slot, _QUESTIONS.get(slot, f"{slot} 값을 알려주세요."))
            for slot in pending[:MAX_QUESTIONS_PER_TURN]
        )

    def questions(self) -> tuple[str, ...]:
        """The next questions to put to the user, at most three.

        Ordered so that the first answers are the ones that unlock a result.
        """
        return tuple(question for _, question in self.prompts())


def _read_direction(raw: Any) -> tuple[str | None, str | None]:
    text = str(raw).strip().lower()
    if text in _DIRECTIONS:
        return _DIRECTIONS[text], None
    return None, "수출 또는 수입 중 하나로 알려주세요."


def _read_amount(raw: Any) -> tuple[Decimal | None, str | None]:
    text = str(raw).strip().replace(",", "").replace("$", "")
    if not text:
        return None, "금액이 비어 있습니다."
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, "금액을 숫자로 알려주세요."
    if amount <= 0:
        return None, "금액은 0보다 커야 합니다."
    return amount, None


def _read_date(raw: Any, field: str) -> tuple[date | None, str | None]:
    if isinstance(raw, date):
        return raw, None
    text = str(raw).strip().replace("/", "-").replace(".", "-")
    try:
        return date.fromisoformat(text), None
    except ValueError:
        return None, f"{field} 날짜를 2026-10-24 형식으로 알려주세요."


def _read_ratio(raw: Any) -> tuple[Decimal | None, str | None]:
    text = str(raw).strip().rstrip("%")
    try:
        ratio = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, "선수금 비율을 숫자로 알려주세요."
    if ratio > 1:
        ratio = ratio / Decimal("100")
    if not 0 <= ratio <= 1:
        return None, "선수금 비율은 0에서 100% 사이여야 합니다."
    return ratio, None


def read_slots(raw: Mapping[str, Any]) -> SlotReading:
    """Normalize whatever the user supplied and report what is still needed.

    A value that cannot be understood is an issue rather than a missing slot:
    the difference matters because the first needs correcting and the second
    needs asking.
    """
    values: dict[str, Any] = dict(MVP_DEFAULTS)
    issues: list[SlotIssue] = []
    provided = {
        key: value
        for key, value in raw.items()
        if value is not None and str(value).strip() != ""
    }

    if "currency" in provided:
        currency = str(provided["currency"]).strip().upper()
        if currency != MVP_DEFAULTS["currency"]:
            issues.append(
                SlotIssue("currency", "지금은 미국 달러 거래만 분석할 수 있습니다.")
            )
        else:
            values["currency"] = currency

    if "payment_method" in provided:
        method = str(provided["payment_method"]).strip().upper()
        if method != MVP_DEFAULTS["payment_method"]:
            issues.append(
                SlotIssue("payment_method", "지금은 T/T 송금 방식만 분석할 수 있습니다.")
            )
        else:
            values["payment_method"] = method

    readers = {
        "direction": _read_direction,
        "amount": _read_amount,
        "expected_payment_date": lambda v: _read_date(v, "결제"),
        "expected_shipment_date": lambda v: _read_date(v, "선적"),
        "contract_date": lambda v: _read_date(v, "계약"),
        "advance_payment_ratio": _read_ratio,
    }
    for field, reader in readers.items():
        if field not in provided:
            continue
        value, problem = reader(provided[field])
        if problem:
            issues.append(SlotIssue(field, problem))
        else:
            values[field] = value

    for field in ("country", "counterparty_id"):
        if field in provided:
            values[field] = str(provided[field]).strip()

    # A slot the user attempted but we could not read is reported once, as an
    # issue. Listing it as missing too would ask for it and correct it in the
    # same breath.
    attempted = {issue.field for issue in issues}
    missing = tuple(
        slot
        for slot in REQUIRED_SLOTS
        if slot not in values and slot not in attempted
    )
    return SlotReading(values=values, missing=missing, issues=tuple(issues))
