"""What this product can decide about a subject, and what it cannot.

§1.1 stops the system from inventing facts, and it does that well: an unstated
company size becomes a question, not a `False`. But there is a second way to
mislead that no fail-closed rule catches — being asked about something the
product does not cover at all, and answering about something else.

A company asking about 제작 자금 was told about its exchange-rate exposure and
shown three K-SURE insurance products. Nothing on the screen was false. Nothing
on the screen said "we do not look at 수출입은행 자금 yet" either, so the
conversation went on as if it were going somewhere.

The held side is derived from the rulepacks rather than written down, so it
cannot drift: adding a rule for a new authority changes what this says without
anyone remembering to edit a sentence. The intended side has to be declared —
it is a statement about the product's scope, and no file contains it.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"
RULEPACKS = KNOWLEDGE_ROOT / "rulepacks"

#: Which rulepack topic answers which section of the answer.
TOPIC_SECTION = {
    "trade_support_case": "support",
    "fx_compliance": "compliance",
}

#: The authorities this product means to cover, in the words a person uses.
#: Declared, not derived — it is a claim about scope, and the gap between it
#: and the rulepacks is the thing worth saying out loud.
INTENDED = {
    "support": {
        # Both name the same body. The second is K-SURE's product delivered
        # through a bank, and listing it separately made the line read
        # "한국무역보험공사 · 한국무역보험공사·금융기관".
        "ksure": "한국무역보험공사",
        "ksure_and_financial_institution": "한국무역보험공사",
        "koreaexim": "한국수출입은행",
        "kodit": "신용보증기금",
        "kibo": "기술보증기금",
        "kosmes": "중소벤처기업진흥공단",
    },
    "compliance": {
        "bank_of_korea": "한국은행",
        "foreign_exchange_bank": "외국환은행",
        "designated_foreign_exchange_bank": "지정거래외국환은행",
    },
}

SECTION_NAME = {"support": "지원제도", "compliance": "신고의무"}


@cache
def held(section: str) -> frozenset[str]:
    """The authorities that actually have rules today."""
    found: set[str] = set()
    for path in sorted(RULEPACKS.glob("*.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for rule in pack.get("rules") or []:
            if TOPIC_SECTION.get(rule.get("topic")) != section:
                continue
            authority = (rule.get("candidate_outcome") or {}).get("authority")
            if authority:
                found.add(authority)
    return frozenset(found)


def missing(section: str) -> tuple[str, ...]:
    """Intended authorities with no rules behind them, in reading order."""
    covered = held(section)
    return tuple(
        name
        for authority, name in INTENDED.get(section, {}).items()
        if authority not in covered
    )


def _particle(word: str) -> str:
    """은 or 는, chosen the way Korean chooses it.

    `은(는)` is what a template writes when it does not know the word it is
    joining, and the last authority in this list changes as rules are added.
    A final consonant decides it, and a syllable carries one at a fixed offset.
    """
    last = ord(word.strip()[-1])
    syllable = 0xAC00 <= last <= 0xD7A3
    return "은" if syllable and (last - 0xAC00) % 28 else "는"


def statement(section: str) -> str:
    """One line about this subject, or nothing when there is nothing to admit.

    Silence when the coverage is complete. A product that recites its limits on
    every turn teaches the reader to skip the line, and then it is not there
    when it matters.
    """
    if section not in INTENDED:
        return ""
    absent = missing(section)
    if not absent:
        return ""
    names = sorted({INTENDED[section][a] for a in held(section) if a in INTENDED[section]})
    subject = SECTION_NAME.get(section, section)
    if not names:
        return f"{subject}는 아직 판정하지 않습니다."
    listed = " · ".join(absent)
    return (
        f"{subject}는 {' · '.join(names)} 제도만 판정합니다. "
        f"{listed}{_particle(absent[-1])} 아직 다루지 않습니다."
    )
