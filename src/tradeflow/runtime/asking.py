"""The facts a judgement is waiting for, as questions the reader can answer.

§5.4 reports exactly what it is missing — `missing_fields` on every candidate
that ran out of facts — and the screen was not reading it. It asked for two
company facts and stopped, because those two were the ones an account used to
carry. So a company that answered everything the screen asked still saw two of
three products come back 「아직 판정하지 못했습니다」, listing conditions nobody
was ever going to be asked about.

That gap was invisible while accounts existed. With sign-in closed, this is the
only way a fact reaches the rules, and a judgement that cannot be closed is a
judgement that may as well not have run.

Not every missing fact is a question. Three kinds:

  - **The company knows it.** 자금 용도, 은행 상담 여부, K-SURE 등급. Ask.
  - **We look it up.** 국별인수방침 인수제한국 여부 — asking the company
    whether its buyer's country is restricted is asking them to make our
    judgement, and their answer would be evidence of nothing.
  - **We already have it.** A day count derivable from dates the company gave
    is not a question; asking would be the product failing to read its own
    input back.

Only the first kind is listed here. The rest are absent on purpose, and the
absence is the statement — `ASKABLE` is the whole set, so a field that is not
in it is never asked, whatever a rule reports.

The wording comes from the fact catalog wherever the catalog has it: the type,
the allowed values and the description are already written there, once, next to
the evidence role each field demands. Only the Korean sentence a person is
asked is here, because the catalog is a contract and a question is not.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"
FACT_CATALOG = KNOWLEDGE_ROOT / "fact_catalog.json"


@cache
def catalog() -> dict[str, dict[str, Any]]:
    """The fact catalog, by field."""
    try:
        raw = json.loads(FACT_CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    facts = raw.get("facts", raw)
    if isinstance(facts, dict):
        return {str(name): value for name, value in facts.items()}
    return {str(item.get("field")): item for item in facts}


#: What the reader is asked, for the facts the reader is the one who knows.
#:
#: Membership is the decision. A field outside this table is never put to the
#: company — not because there is no sentence for it, but because their answer
#: would not be evidence of the thing the rule needs.
ASKABLE: dict[str, dict[str, Any]] = {
    "financing.purpose": {
        "question": "필요한 자금이 어떤 용도인가요?",
        "labels": {
            "trade_finance": "무역금융",
            "recognized_export_finance": "인정 수출실적 자금",
            "trade_bill_acceptance": "무역어음 인수",
            "export_material_import_lc": "수출용 원자재 수입 신용장",
            "recognized_export_promotion_fund": "수출진흥자금",
            "other": "그 밖의 용도",
        },
    },
    "financing.has_bank_consultation": {
        "question": "거래 은행과 보증부 대출을 상담해 보셨나요?",
        "labels": {"true": "상담했습니다", "false": "아직 상담 전입니다"},
    },
    "company.ksure_exporter_grade": {
        "question": "K-SURE 수출자 신용등급을 아시나요?",
        # UNKNOWN is an answer, not a refusal to answer: a company that has
        # never been graded is a different case from one that has not told us,
        # and the rules read them differently.
        "labels": {"UNKNOWN": "모릅니다 · 등급이 없습니다"},
    },
    "counterparty.ksure_importer_grade": {
        "question": "수입자(구매자)의 K-SURE 신용등급을 아시나요?",
        "labels": {"UNKNOWN": "모릅니다 · 등급이 없습니다"},
    },
}


#: Facts this product works out, and the trade detail each one needs.
#:
#: The fact itself is never put to the company — a term they typed could
#: disagree with the dates beside it on screen, and nothing would say which one
#: the rule used. What is asked for is the missing input, which is a fact about
#: their own trade and one they plainly know.
#:
#: So the question changes but the arithmetic does not, and the answer arrives
#: as a trade detail rather than as a judgement about a trade.
DERIVED: dict[str, dict[str, Any]] = {
    "trade.payment_term_days": {
        "slot": "expected_shipment_date",
        "question": "언제 선적하시나요?",
        "kind": "date",
    },
}


def _options(field: str, entry: dict[str, Any]) -> list[dict[str, str]]:
    """The answers on offer, in the catalog's own order.

    Booleans get two; enums get theirs. Anything else is typed rather than
    chosen, and returns nothing.
    """
    labels = ASKABLE[field].get("labels") or {}
    if entry.get("type") == "boolean":
        return [
            {"value": value, "label": labels.get(value, value)}
            for value in ("true", "false")
        ]
    if entry.get("type") == "enum":
        return [
            {"value": value, "label": labels.get(value, value)}
            for value in entry.get("allowed_values") or []
        ]
    return []


def slots_of(fields: Any = None) -> frozenset[str]:
    """The trade slots the derived questions ask for.

    Read from `DERIVED` so the caller that collects what a trade already has
    does not keep its own copy of the list.
    """
    return frozenset(entry["slot"] for entry in DERIVED.values())


def questions(
    result: dict[str, Any],
    *,
    already: dict[str, str] | None = None,
    #: `(case_id, slot)` for every trade detail the company has already given.
    #: A derived fact can legitimately fail to derive — a payment that lands
    #: before shipment is a prepayment, and no term comes out of it — and
    #: without this the rule keeps reporting the fact missing and the screen
    #: keeps asking the same question of someone who has already answered it.
    supplied: frozenset[tuple[str, str]] = frozenset(),
) -> list[dict[str, Any]]:
    """One question per fact still blocking a judgement, in rule order.

    Deduplicated across products: two rules can want the same grade, and being
    asked for it twice would say the screen is not reading its own answers.
    `already` drops what this turn was told, so a fact supplied once is not
    asked again on the next turn.
    """
    answered = set(already or {})
    facts = catalog()
    asked: dict[str, dict[str, Any]] = {}

    for candidate in result.get("support_candidates") or []:
        if candidate.get("status") != "insufficient_information":
            continue
        for field in candidate.get("missing_fields") or []:
            if field in answered or field in asked:
                continue
            # Why it is being asked, in the name of the thing it opens. A
            # question with no stated purpose reads as a form.
            opens = candidate.get("title") or ""
            if field in DERIVED:
                # The answer is a trade detail, so it goes back the way a trade
                # detail does. Absent it the fact stays missing and the rule
                # keeps saying so, which is the correct answer rather than a
                # gap: a term computed from a shipment date nobody gave would
                # be manufactured out of a blank field.
                #
                # And it goes back to *this* trade. The judgement names the one
                # it is about, and the screen was writing every slot answer onto
                # the last trade described — so a company with an export and an
                # import answered 「언제 선적하시나요」 onto the import, the
                # export's term still did not derive, and the same question came
                # back on every turn after that.
                slot = DERIVED[field]["slot"]
                case_id = candidate.get("subject_id")
                if (case_id, slot) in supplied:
                    continue
                asked[field] = {
                    "field": slot,
                    "answer_as": "case",
                    "case_id": case_id,
                    "question": DERIVED[field]["question"],
                    "opens": opens,
                    "kind": DERIVED[field]["kind"],
                    "options": [],
                }
                continue
            if field not in ASKABLE:
                continue
            entry = facts.get(field)
            if entry is None:
                continue
            asked[field] = {
                "field": field,
                "answer_as": "fact",
                "question": ASKABLE[field]["question"],
                "opens": opens,
                "kind": entry.get("type") or "text",
                "options": _options(field, entry),
            }
    return list(asked.values())


def accepts(field: str, value: str) -> bool:
    """Whether the catalog would recognise this answer for this field.

    Checked before the value is carried any further, so a value the rules
    would reject is refused at the door with the field named rather than
    disappearing into an assertion nobody can trace.
    """
    if field not in ASKABLE:
        return False
    entry = catalog().get(field)
    if entry is None:
        return False
    kind = entry.get("type")
    if kind == "boolean":
        return value in ("true", "false")
    if kind == "enum":
        return value in (entry.get("allowed_values") or [])
    return bool(value.strip())


def as_stated(field: str, value: str) -> Any:
    """The answer in the type the rules compare against."""
    kind = (catalog().get(field) or {}).get("type")
    if kind == "boolean":
        return value == "true"
    if kind == "integer":
        return int(value)
    return value


def evidence_role(field: str) -> str | None:
    """The role the catalog demands for this fact.

    Read rather than chosen. A fact carried under the wrong role is a fact the
    rules were never meant to accept, and deciding the role at the call site is
    how that happens.
    """
    return (catalog().get(field) or {}).get("evidence_role")
