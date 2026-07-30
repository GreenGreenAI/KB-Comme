"""What a sentence is doing, as distinct from what it is about.

`intent.py` reads the subject — 환율, 지원제도, 신고의무. This reads the kind of
turn, and the two are not the same question. Without it the product had exactly
one move and applied it to everything:

    안녕                              → 수출/수입 여부, 금액, 날짜를 알려주세요
    너 뭐 할 수 있어?                  → 수출/수입 여부, 금액, 날짜를 알려주세요
    환율이 요즘 어때?                  → 수출/수입 여부, 금액, 날짜를 알려주세요

Three different things to say, one answer. The reason is structural rather than
careless: §4.2[1] counts the slots a trade is missing, and a greeting is missing
all three exactly as a half-described trade is. Counting cannot tell them apart,
so something has to read the sentence itself.

Deterministic and keyword-based, like `read_intent`, and for the same reason —
what the product does next must not vary between two identical sentences. The
consequence of misreading is mild here: a greeting read as a question gets an
answer it did not ask for, which is a worse turn, not a wrong judgement. Nothing
downstream computes anything from this.
"""

from __future__ import annotations

import re

#: The sentence is only a greeting. Answering it with three questions is the
#: product asking the user to fill in a form before saying hello back.
GREETING = "greeting"

#: The sentence asks about the product. The answer is already in the code —
#: which authorities have rules, which workers exist — and needs no trade.
ABOUT = "about"

#: The sentence asks about a subject but describes no trade. Some of it can be
#: answered from what is held (today's rate, the recent window); the rest needs
#: the trade, and that is what to ask for — after answering what does not.
TOPIC = "topic"

#: The sentence describes a trade, complete or not. §4.2[1] as it stands.
TRADE = "trade"

_GREETINGS = (
    "안녕",
    "반가",
    "하이",
    "ㅎㅇ",
    "hello",
    "hi",
    "여보세요",
    "처음",
)

_ABOUT = (
    "뭐 할 수 있",
    "뭘 할 수 있",
    "무엇을 할 수 있",
    "무슨 일을 하",
    "뭐 하는",
    "어떤 걸 할 수 있",
    "어떤 것을 할 수 있",
    "어떻게 쓰",
    "어떻게 사용",
    "사용법",
    "소개",
    "너 뭐야",
    "이거 뭐야",
    "무슨 서비스",
    "도움말",
)

#: The polite tail a greeting stem takes. Korean inflects the greeting rather
#: than appending to it — 안녕 becomes 안녕하세요, 반가 becomes 반가워요 — so
#: removing the stem alone leaves 하세요 behind, and a leftover is what tells
#: this module the sentence went on to say something. Longest first: stripping
#: 요 before 하세요 would leave 하세 sitting there looking substantive.
_ENDINGS = (
    "하십니까",
    "하세요",
    "하셨어",
    "합니다",
    "습니다",
    "십니다",
    "이에요",
    "예요",
    "해요",
    "워요",
    "어요",
    "아요",
    "네요",
    "세요",
    "하이",
    "여",
    "요",
    "용",
    "염",
    "다",
)

#: Punctuation and spacing only. A greeting is short and the words that carry
#: it are short too, so anything that survives this and is not a greeting is
#: the sentence saying something else.
_TRIM = re.compile(r"[\s.,!?~ㅋㅎ♥❤👋]+")


def read_kind(text: str | None, *, heard: dict[str, str] | None, topics: tuple[str, ...]) -> str:
    """The kind of turn this is.

    `heard` is what the slot reader found and `topics` what `read_intent` read.
    Both are passed in rather than re-derived: this module must not become a
    second, disagreeing reading of the same sentence.

    A trade wins over everything. "안녕하세요, 10월에 10만 달러 받습니다" is a
    trade with a greeting attached, and answering the greeting would drop the
    trade — the one thing in the sentence that cost the user effort to write.
    """
    if heard:
        return TRADE
    if not text or not text.strip():
        return TRADE

    lowered = text.lower()
    if any(word in lowered for word in _ABOUT):
        return ABOUT
    if topics:
        return TOPIC
    if _is_only_greeting(lowered):
        return GREETING
    # Something was said that is neither a greeting, a question about the
    # product, nor a subject we recognise. Asking what the trade is remains the
    # honest move — the alternative is a guess about what they meant.
    return TRADE


def _is_only_greeting(lowered: str) -> bool:
    """A greeting and nothing else.

    "안녕하세요, 수출 관련해서 여쭤볼 게 있는데요" is not this. What is left
    after the greeting words are removed is what decides, so a sentence that
    opens politely and then says something keeps its something.
    """
    if not _TRIM.sub("", lowered):
        return False
    if not any(word in lowered for word in _GREETINGS):
        return False
    remainder = lowered
    for word in _GREETINGS:
        remainder = remainder.replace(word, "")
    for ending in _ENDINGS:
        remainder = remainder.replace(ending, "")
    return not _TRIM.sub("", remainder)
