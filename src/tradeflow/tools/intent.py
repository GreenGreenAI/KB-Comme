"""Reading what a sentence is asking about.

§4.2[2] lists three inputs for the orchestrator — `TradeCase[]`,
`CompanyProfile` and 사용자 의도 — and the routing table only uses the first
two. This module supplies the third.

**Intent orders the answer; it does not narrow it.** That distinction is the
whole design, so it is worth stating why. §2 says the target user does not know
their own exposure. Someone who asks "환율이 얼마나 움직여요?" still has a
filing duty if their contract nets invoices, and a product that computed only
what was asked would never tell them. Answering only the question is a search
engine; §4.2[6] already draws that line for excluded candidates ("후보 목록만
주는 서비스는 검색기지만, 왜 이건 안 되는지를 주는 서비스는 자문이다").

So what the question changes is which section the reader meets first, not which
sections exist. The workers are chosen by the trade data (routing.py); the
order is chosen here.

The reading is keyword-based and deterministic. An LLM will eventually phrase
the answer (§4.2[9]) but must not be the thing that decides what gets computed
or what gets hidden.
"""

from __future__ import annotations

import re
from typing import Any

#: Response sections a question can be about, each with the words that name it.
#:
#: Matching is on the surface form the user is likely to type, not on our own
#: vocabulary: a company says 보험 and 지원금, not 지원제도 매칭.
TOPIC_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "market_scenario",
        ("환율", "환시세", "시세", "변동성", "얼마까지", "오르", "내리", "떨어"),
    ),
    (
        "hedge",
        # No 환변동보험. It is a hedging instrument and a K-SURE scheme both,
        # and naming it is asking about the scheme — 「환변동보험이란 게
        # 뭔가요」 read as a hedge question and the answer opened with
        # 「헤지비율은 거래가 있어야 계산합니다」, which is not what was asked.
        # A sentence that wants the hedge as well says so: 「환변동보험으로
        # 헤지할까요」 carries 헤지 and reads as both.
        ("헤지", "헷지", "선물환", "위험 관리", "리스크 관리", "막을"),
    ),
    (
        "exposure",
        # No bare 자금. "제작에 들어갈 자금이 부족합니다" is a question about
        # raising money, and reading it as exposure made 자금 the first topic
        # in the sentence — so a company asking about 무역금융 was answered
        # about its exchange-rate exposure, in that order, and told which
        # inputs the exposure calculation wanted. 자금 alone does not say
        # which of the two it is; the verb beside it does.
        (
            "노출",
            "현금",
            "자금이 얼마",
            "자금은 얼마",
            "필요 자금",
            "필요한 자금",
            "얼마나 받",
            "얼마나 내",
            "손해",
            "손실",
            "이익",
        ),
    ),
    (
        "support",
        (
            "지원",
            "보조금",
            "정책자금",
            "보증",
            "보험",
            "제도",
            "혜택",
            "무역금융",
            # Scheme names. The company says the product it heard of, not the
            # category we file it under.
            "환변동보험",
            "단기수출보험",
            "수출신용보증",
            "수출보험",
            # Raising money, not measuring exposure.
            "제작 자금",
            "제작에 들어갈 자금",
            "생산 자금",
            "운전자금",
            "자금이 부족",
            "자금 조달",
            "자금을 조달",
            "대출",
            "융자",
        ),
    ),
    (
        "compliance",
        # No bare 법: it matches inside 방법, so "막을 방법 있나요" read as a
        # question about statutes. Korean compounds have no space to anchor on,
        # so short words have to be specific enough to stand alone.
        (
            "신고",
            "규정",
            "외국환거래법",
            "법령",
            "의무",
            "위반",
            "상계",
            "제3자",
            "상호계산",
        ),
    ),
)

#: Order used when the sentence asks nothing in particular — a bare trade
#: description, which is how most sessions start. Exposure first because it is
#: the figure the user came without knowing.
DEFAULT_ORDER = (
    "exposure",
    "market_scenario",
    "hedge",
    "support",
    "compliance",
)

_WORD = re.compile(r"\s+")


def read_intent(text: str | None) -> tuple[str, ...]:
    """Topics the sentence asks about, in the order it raises them.

    Returns an empty tuple when the sentence names none — a trade description
    is not a question, and inventing an intent for it would reorder the answer
    on no evidence.
    """
    if not text or not text.strip():
        return ()

    normalized = _WORD.sub(" ", text)
    hits: list[tuple[int, str]] = []
    for topic, words in TOPIC_PATTERNS:
        positions = [
            normalized.find(word) for word in words if word in normalized
        ]
        if positions:
            hits.append((min(positions), topic))

    hits.sort()
    return tuple(topic for _, topic in hits)


def section_order(intent: tuple[str, ...]) -> tuple[str, ...]:
    """Every section, with the ones asked about brought to the front.

    Sections the question did not mention keep their default order behind the
    ones it did. Nothing is dropped: a section removed because it was not asked
    about would be a section the reader never learns exists.
    """
    asked = tuple(dict.fromkeys(t for t in intent if t in DEFAULT_ORDER))
    rest = tuple(topic for topic in DEFAULT_ORDER if topic not in asked)
    return asked + rest


def describe(intent: tuple[str, ...]) -> dict[str, Any]:
    """What was read, for the response to carry.

    The reader can see that a reordering happened and why, rather than finding
    the sections in a different place each time for no stated reason.
    """
    return {
        "topics": list(intent),
        "section_order": list(section_order(intent)),
        "reordered": bool(intent),
    }
