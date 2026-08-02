"""The judgements, as sentences.

The screen used to render the decision packet's shape: a grey card of collapsed
rows, each holding a title, a status chip and a list. That is a record, and a
record is something you audit, not something you read. A company asked whether
it could get support and had to open three folds to find out.

So the same judgements are written out. Not by §4.2[9] — a model that can say
「환변동보험이 있습니다」 can also say 「자격이 됩니다」, and the whole division
rests on it not being able to. These sentences are assembled here, from what the
rules decided and the words the rulepack wrote its conditions in. Nothing is
concluded that a rule did not conclude; what changes is that it is legible.

Three things stay visual, because a sentence is the wrong shape for them: the
rate band (a position on a scale), the payoff comparison (three choices at three
rates), and the cashflow figures. A picture of a number is worse than the number;
a sentence about a range is worse than the range.
"""

from __future__ import annotations

from typing import Any

#: Statuses that mean the rules reached a verdict rather than ran out of facts.
_SETTLED = "insufficient_information"


def _particle(word: str, pair: tuple[str, str]) -> str:
    """The one Korean would choose, by whether the last syllable closes.

    `은(는)` is what a template writes when it does not know the word it is
    joining, and every word joined here is a product name or a rule condition
    that changes with the trade.

    The last *syllable* decides, not the last character. Product names end in
    brackets — 「단기수출보험(선적후·개별)」 — and reading the bracket gave 는
    where 별 wanted 은.
    """
    for character in reversed(word.strip()):
        code = ord(character)
        if not 0xAC00 <= code <= 0xD7A3:
            continue
        return pair[0] if (code - 0xAC00) % 28 else pair[1]
    return pair[1]


#: The three the assembled sentences need. Each is (after a closed syllable,
#: after an open one).
TOPIC = ("은", "는")
OBJECT = ("을", "를")
SUBJECT = ("이", "가")
#: 「…이면」 / 「…면」. The branch conditions end in whatever the rulepack wrote.
CONDITIONAL = ("이면", "면")


#: How many items a sentence may name before it becomes a list. Past this the
#: reader stops reading the sentence and starts scanning it, and the sentence
#: was the point.
NAMED = 2


def _joined(words: list[str]) -> str:
    return " · ".join(words)


def _some(words: list[str]) -> str:
    """The first few by name, the rest counted.

    Every condition and every document used to be named inline. Five checks,
    four requirements and six document titles in three paragraphs is a record
    again, in sentence clothing — the reader has to hold two lists at once to
    tell which requirement belongs to which product. The full lists are still
    carried; they are just not in the first thing anyone reads.
    """
    # The count is always stated, even for a short list. §4.2[9]'s rewrite may
    # only quote numbers it was given, and a list without its count made the
    # model count for itself — arithmetically right, and an invention by the
    # only definition that matters here.
    if len(words) <= NAMED:
        return f"{_joined(words)} {len(words)}가지"
    return f"{_joined(words[:NAMED])} 등 {len(words)}가지"


#: How many trades are on screen is not a fact about a rule.
#:
#: Every rule runs against every trade, so the packet holds one judgement per
#: (trade, rule) — which is right, because a duty and an eligibility both
#: attach to a trade and the audit has to show which. These paragraphs never
#: name a trade, so the same judgement arrived once per trade: three trades
#: printed 「다자간 상계면 한국은행에 신고합니다」 three times in a row and
#: counted fourteen undecided rules as forty-three.
def _rule_key(item: dict[str, Any]) -> str:
    """What makes two judgements the same judgement, said in this paragraph.

    `rule_id` on anything the packet produced; the title is the fallback for a
    hand-written case, and it names the same thing.
    """
    return str(item.get("rule_id") or item.get("title") or id(item))


def _one_per_rule(
    items: Any, *, prefer: Any = lambda new, kept: False
) -> list[dict[str, Any]]:
    """One judgement per rule, choosing which copy speaks for the rest.

    `prefer(new, kept)` decides when a later copy replaces an earlier one.
    Copies can disagree — a product can be settled on one trade and short of a
    fact on another — and the sentence cannot say which trade it means, so the
    weaker claim is the one kept. Saying 「조건을 충족합니다」 on the strength of
    one of two trades would be this paragraph deciding something no rule did.
    """
    kept: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _rule_key(item)
        seen = kept.get(key)
        if seen is None or prefer(item, seen):
            kept[key] = item
    return list(kept.values())


def _weaker(new: dict[str, Any], kept: dict[str, Any]) -> bool:
    """A judgement still short of a fact outranks one that reached a verdict."""
    return new.get("status") == _SETTLED and kept.get("status") != _SETTLED


def _louder(new: dict[str, Any], kept: dict[str, Any]) -> bool:
    """A rule the company's own words put in play outranks one they did not.

    §5.5's direction: a branch that might apply is stated, never dropped.
    """
    return bool(new.get("engaged")) and not kept.get("engaged")


def support(result: dict[str, Any]) -> list[str]:
    """What the eligibility rules decided, in paragraphs.

    One for the products that reached a verdict, one for the products still
    short of a fact, and one for what to do about the first. Products with
    nothing to say produce no paragraph rather than an empty heading.
    """
    candidates = _one_per_rule(result.get("support_candidates") or [], prefer=_weaker)
    if not candidates:
        return []

    said: list[str] = []
    settled = [c for c in candidates if c.get("status") != _SETTLED]
    open_ones = [c for c in candidates if c.get("status") == _SETTLED]

    for candidate in settled:
        title = candidate.get("title") or ""
        met = [
            check["description"]
            for check in candidate.get("checks") or []
            if check.get("status") == "passed"
        ]
        line = f"{title}{_particle(title, TOPIC)} 조건을 충족합니다."
        if met:
            line += f" 확인한 조건은 {len(met)}가지입니다."
        if candidate.get("status") == "expert_confirmation_required":
            line += " 초안 규칙이라 공식 확인을 받으셔야 합니다."
        said.append(line)

    # One sentence per product. Joined into a single paragraph they ran to four
    # lines and the reader had to hold two lists at once to tell which
    # requirement belonged to which product.
    for candidate in open_ones:
        title = candidate.get("title") or ""
        wants = [
            check["description"]
            for check in candidate.get("checks") or []
            if check.get("status") == "uncertain"
        ]
        if not wants:
            continue
        listed = _some(wants)
        said.append(
            f"{title}{_particle(title, TOPIC)} 아직 판정하지 못했습니다. "
            f"{listed}{_particle(listed, OBJECT)} 알려주시면 판정합니다."
        )

    return said


def compliance(result: dict[str, Any]) -> list[str]:
    """What §5.5's rules made of the trade structure the company described.

    The rules the company's own words put in play come first and by name; the
    ones that do not know whether they apply are counted. Both are said —
    「해당 없음」 and 「아직 모름」 are different answers and §5.5 is explicit
    that the second must never be read as the first.
    """
    findings = _one_per_rule(
        (
            f
            for f in (result.get("risk_findings") or [])
            if (f.get("outcome") or {}).get("kind") != "support_candidate"
        ),
        prefer=_louder,
    )
    if not findings:
        return []

    engaged = [f for f in findings if f.get("engaged")]
    rest = len(findings) - len(engaged)
    said: list[str] = []

    if engaged:
        said.append(
            f"말씀하신 거래 구조는 신고 대상이 될 수 있습니다. "
            f"어느 쪽인지는 {len(engaged)}가지 갈래로 갈립니다."
        )

    # What the rule would mean if it applies, not which field is missing. The
    # rulepack writes every condition as a sentence — 「양자간 상계」, 「일방
    # 금액 미화 5천달러 초과」 — and names the authority, the action and the
    # timing in its outcome. All of it was being withheld behind a list of
    # field names, so the answer said less than the rules knew.
    for finding in engaged:
        outcome = finding.get("outcome") or {}
        authority = AUTHORITY_NAME.get(outcome.get("authority"), outcome.get("authority"))
        act = FILING_ACTION.get(outcome.get("action"), "신고")
        when = TIMING.get(outcome.get("timing"), "")
        conditions = [
            check["description"]
            for check in finding.get("checks") or []
            if check["description"] not in SHARED_CONDITION
        ]
        if not conditions:
            continue
        listed = _joined(conditions)
        said.append(
            f"{listed}{_particle(listed, CONDITIONAL)} "
            f"{authority}에 {act}합니다{when}."
        )

    if engaged:
        said.append(
            "기준은 거래금액이 아니라 상계하는 채권과 채무 중 작은 금액입니다. "
            "그 금액이 미화 5천 달러 이하이거나 신고예외에 해당하면 "
            "신고 의무가 없습니다."
        )
        said.append("어느 갈래인지 정하려면 상계 당사자 수와 상계금액을 알려주세요.")

    if rest:
        said.append(
            f"말씀해 주신 것으로는 해당 여부를 알 수 없는 규칙이 {rest}건 "
            "더 있습니다. 신고가 불필요하다는 판정은 아닙니다."
        )
    return said


#: Conditions every netting rule shares. Repeating them once per branch turned
#: three sentences into three copies of the same qualifier.
SHARED_CONDITION = {
    "거주자와 비거주자 간 채권·채무 상계",
    "일방 금액 미화 5천달러 초과",
    "그 밖의 신고예외가 확인되지 않음",
    "신고예외가 확인되지 않음",
}

FILING_ACTION = {"report": "보고", "file": "신고"}

TIMING = {
    "confirm_before_execution": " — 상계 전에",
    "confirm_with_authority": " — 시점은 거래 외국환은행에 확인하세요",
}


def _one_per_errand(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The same errand once, however many trades produced it.

    An action is keyed by where you go and what you do there — two trades at
    the same authority for the same product are one visit, and 「다음은
    한국무역보험공사 상담 및 청약입니다」 twice is not two things to do.
    """
    kept: dict[tuple, dict[str, Any]] = {}
    for action in result.get("next_actions") or []:
        key = (
            action.get("authority"),
            action.get("action"),
            tuple(sorted(str(p) for p in action.get("product_ids") or [])),
            tuple(action.get("required_documents") or []),
        )
        kept.setdefault(key, action)
    return list(kept.values())


def actions(result: dict[str, Any]) -> list[str]:
    """What the reader has to go and do, and with which documents."""
    said: list[str] = []
    for action in _one_per_errand(result):
        authority = AUTHORITY_NAME.get(action.get("authority"), action.get("authority"))
        line = f"다음은 {authority} {ACTION_NAME.get(action.get('action'), '상담 및 신청')}입니다."
        documents = action.get("required_documents") or []
        if documents:
            line += f" 필요서류는 {len(documents)}건입니다."
        said.append(line)
    return said


AUTHORITY_NAME = {
    "ksure": "한국무역보험공사",
    "ksure_and_financial_institution": "한국무역보험공사와 거래 금융기관",
    "bank_of_korea": "한국은행",
    "foreign_exchange_bank": "외국환은행",
    "designated_foreign_exchange_bank": "지정거래외국환은행",
}

ACTION_NAME = {
    "consult_and_apply_for_ksure_product": "상담 및 청약",
    "consult_and_apply_for_preshipment_guarantee": "선적전 보증 상담 및 신청",
    "file_with_authority": "신고",
}


def detail(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The full lists, for the reader who wants them.

    Carried rather than dropped: what a rule checked and what a form requires
    is exactly what someone about to apply needs, and §6.1 asks that a
    judgement be inspectable. It is one fold away instead of in the first
    paragraph.
    """
    # Deduped the same way the sentences are. The fold is a longer look at the
    # same judgements, and a title repeated per trade also collided as a key on
    # the way to the screen.
    rows: list[dict[str, Any]] = []
    for candidate in _one_per_rule(
        result.get("support_candidates") or [], prefer=_weaker
    ):
        rows.append(
            {
                "title": candidate.get("title") or "",
                "met": [
                    check["description"]
                    for check in candidate.get("checks") or []
                    if check.get("status") == "passed"
                ],
                "wanted": [
                    check["description"]
                    for check in candidate.get("checks") or []
                    if check.get("status") == "uncertain"
                ],
            }
        )
    for action in _one_per_errand(result):
        documents = action.get("required_documents") or []
        if documents:
            rows.append({"title": "필요서류", "met": [], "wanted": documents})
    return rows


def sources(result: dict[str, Any]) -> list[dict[str, str]]:
    """Every source the answer rests on, once, in the order it was used."""
    seen: dict[str, dict[str, str]] = {}
    for candidate in result.get("support_candidates") or []:
        for source in candidate.get("sources") or []:
            seen.setdefault(source["source_id"], source)
    return list(seen.values())
