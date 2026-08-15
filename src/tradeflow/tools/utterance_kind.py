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

#: Nothing above recognised it.
#:
#: This used to be TRADE — not as a reading, but as somewhere to put whatever
#: was left over, on the grounds that asking for a trade beats guessing at a
#: meaning. That was the honest move while a greeting was the only other thing
#: this module could see. It stopped being one once the sentence could be
#: answered instead: 「고마워」 is not a trade description, and calling it one
#: made the intake funnel the default for every sentence nobody had written a
#: rule for.
#:
#: Kept apart from TRADE because the difference decides who answers. TRADE
#: means slots were read and §4.2[1] has something to work with. This means
#: nothing was read and something still has to decide what the sentence was
#: doing — which is a judgement, and one this module is not equipped to make.
UNCLEAR = "unclear"

#: The sentence continues the last one. 「왜?」 「그럼?」 「더 자세히」 name no
#: subject and describe no trade, so every reading above returns nothing and the
#: sentence fell through to TRADE — a two-letter question was answered by asking
#: for an amount and a settlement date.
#:
#: What it is about is the previous turn's subject. That is the only thing
#: inherited: *ordering*, never facts. A follow-up that could also carry a trade
#: forward would let a sentence already answered describe its trade a second
#: time, which is the hole `asked_about` was written to avoid.
FOLLOW_UP = "follow_up"

#: Words that only make sense pointing at something already said. Kept short and
#: literal on purpose — a long list would start catching sentences that stand on
#: their own, and a sentence wrongly read as a follow-up inherits an order it
#: never asked for.
_FOLLOW_UP = (
    "왜",
    "어째서",
    "그럼",
    "그러면",
    "그거",
    "그건",
    "그게",
    "그 부분",
    "더 자세",
    "자세히",
    "무슨 뜻",
    "어떻게 해야",
    "어떻게 하",
    "방금",
    "아까",
)

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
    if _describes_a_trade(heard):
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
    # Points at something already said and adds nothing of its own. It has to be
    # read after `topics`: 「그럼 신고는?」 names a subject, and a sentence that
    # says what it is about does not need the last one to say it.
    if continues(lowered):
        return FOLLOW_UP
    # Something was said and none of the readings above recognised it. Saying
    # so is the whole of what this module knows; deciding what to do about it
    # belongs to the caller, which can ask.
    return UNCLEAR


#: What makes a sentence a description of a trade rather than a mention of one.
#:
#: A direction on its own does not. 「일반형 **수출** 환변동보험에 대해 설명해줘」
#: reads 수출 and nothing else, and the rule that any slot means a trade sent it
#: down the funnel: the product asked for an amount and a settlement date from
#: someone who had asked what a product was. Every K-SURE name carries a
#: direction — 단기**수출**보험, **수입**금융 — so naming a product looks like
#: describing a trade under that rule.
#:
#: An amount or a date has no reason to appear except from a trade, and intake
#: says the same thing from the other side: a direction alone is never `ready`.
TRADE_SLOTS = ("amount", "expected_payment_date")


def continues(text: str | None) -> bool:
    """Whether this sentence points at the last one.

    Exported because two places need the same reading and must not disagree
    about it: this module, to say what kind of turn it is, and the web layer,
    to decide whose subject the answer is ordered by. A second copy of the word
    list would drift, and the drift would show as a sentence that reads as a
    follow-up in one place and as a new question in the other.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(word in lowered for word in _FOLLOW_UP)


#: The follow-up that has an answer waiting rather than only an order. Every
#: rule records what it checked; 「왜?」 is the question those records answer.
_ASKS_WHY = ("왜", "어째서", "무슨 근거", "어떤 근거", "근거가")


def asks_why(text: str | None) -> bool:
    return bool(text) and any(word in text.lower() for word in _ASKS_WHY)


def _describes_a_trade(heard: dict[str, str] | None) -> bool:
    return bool(heard) and any(heard.get(slot) for slot in TRADE_SLOTS)


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
