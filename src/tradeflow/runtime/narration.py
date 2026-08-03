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

from datetime import date
from typing import Any

#: Statuses that mean the rules reached a verdict rather than ran out of facts.
_SETTLED = "insufficient_information"


def funding_window(result: dict[str, Any]) -> dict[str, Any] | None:
    """When the money runs short, and for how long.

    The screen showed 「자금 공백 60,000 USD」 and nothing else. An amount with
    no date is a worry; an amount with a date is a task — the company either
    has 60,000 dollars on 8월 25일 or it has to arrange them, and which of
    those it is cannot be read off the figure alone.

    Everything needed was already in the response. `analyze_exposure` walks the
    trades in settlement order and records the running balance at each one, so
    the day the balance first goes negative and the day it comes back are two
    lookups in a list the screen was already receiving and ignoring.

    A gap that never closes inside the described trades keeps its start and
    says nothing about an end. Inventing one would mean guessing at a trade
    the company has not mentioned.
    """
    events = (result.get("cashflow_analysis") or {}).get("events") or []
    opened: str | None = None
    closed: str | None = None
    for event in events:
        gap = _amount(event.get("funding_gap"))
        if gap > 0 and opened is None:
            opened = event.get("event_date")
        elif opened is not None and gap == 0:
            closed = event.get("event_date")
            break
    if opened is None:
        return None

    days = _days_between(opened, closed)
    said = _day_of(opened)
    if said is None:
        return None
    return {
        "from": opened,
        "until": closed,
        "days": days,
        # Assembled here rather than on the screen: this is a sentence about a
        # calculation, and the rest of them are written in this module.
        "said": f"{said}부터 {days}일" if days else f"{said}부터",
    }


def _amount(raw: Any) -> float:
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return 0.0


def _day_of(iso: str | None) -> str | None:
    try:
        when = date.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    return f"{when.month}월 {when.day}일"


def _days_between(start: str | None, end: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(end)) - date.fromisoformat(str(start))).days
    except (TypeError, ValueError):
        return None


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

    # One sentence per product, from the same writer `grounded` uses. Joined
    # into a single paragraph they ran to four lines and the reader had to hold
    # two lists at once to tell which requirement belonged to which product.
    #
    # Two copies of this wording existed for about an hour and that was long
    # enough to see the problem: the block under a claim and the summary above
    # it are the same assertion, and a reader who finds them differently worded
    # has to work out whether they are also differently meant.
    for candidate in settled + open_ones:
        checks = candidate.get("checks") or []
        line = _support_claim(
            candidate,
            [c["description"] for c in checks if c.get("status") == "passed"],
            [c["description"] for c in checks if c.get("status") == "uncertain"],
        )
        if line:
            said.append(line)

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


def because(result: dict[str, Any]) -> list[str]:
    """What each verdict rested on, by name.

    「왜?」 is the one follow-up this product can answer well, because the answer
    is already in the packet: every rule records the conditions it checked and
    the sources it read them from. The screen kept them one fold away — which is
    right when nobody asked, and wrong the moment somebody does.

    The conditions are named here rather than counted. 「확인한 조건은
    5가지입니다」 is what the first answer says, and repeating it in reply to
    「왜?」 would be the product saying the same thing louder.

    Only what reached a verdict. A rule still short of a fact has no reason yet
    — it has a question, and `support()` already asks it.
    """
    said: list[str] = []
    for candidate in _one_per_rule(
        result.get("support_candidates") or [], prefer=_weaker
    ):
        if candidate.get("status") == _SETTLED:
            continue
        met = [
            check["description"]
            for check in candidate.get("checks") or []
            if check.get("status") == "passed"
        ]
        if not met:
            continue
        title = candidate.get("title") or ""
        listed = _joined(met)
        said.append(f"{title}{_particle(title, TOPIC)} {listed}을 확인했습니다.")

    for finding in _one_per_rule(
        (
            f
            for f in (result.get("risk_findings") or [])
            if (f.get("outcome") or {}).get("kind") != "support_candidate"
        ),
        prefer=_louder,
    ):
        if not finding.get("engaged"):
            continue
        conditions = [
            check["description"]
            for check in finding.get("checks") or []
            if check["description"] in SHARED_CONDITION
        ]
        if not conditions:
            continue
        listed = _joined(conditions)
        said.append(f"신고 갈래가 열린 것은 {listed}이기 때문입니다.")
        break

    return said


def read_back(heard: dict[str, Any] | None) -> str | None:
    """What was read out of the sentence, said back.

    The screen had this for the turns that could not answer — 「수출 · 100,000
    USD · 2026-10-24로 이해했습니다」 — and not for the turns that could. So a
    company whose sentence was understood completely got no sign that it was,
    and the answer opened on what it still needed. The one turn where being
    heard is worth confirming is the one where something was heard.

    Three of the six fields were missing from that older line as well. The
    shipment date is what settles 「결제기간 2년 이내」 and the country is what
    국별인수방침 is read against — a company that mentioned them and saw them
    left out has no way to tell whether they were ignored or merely unsaid.

    Built from `heard` and not from the trade on file. `heard` is what this
    sentence produced; the trade is everything ever said about it, and 「읽었
    습니다」 about a value the reader typed three turns ago is a claim about
    the wrong sentence.
    """
    if not heard:
        return None

    from tradeflow.tools.utterance import country_name

    said: list[str] = []
    direction, amount = heard.get("direction"), heard.get("amount")
    if amount:
        money = f"{_amount(amount):,.0f} {heard.get('currency') or 'USD'}"
        said.append(f"{direction} {money}" if direction else money)
    elif direction:
        said.append(str(direction))

    country = country_name(heard.get("country"))
    if country:
        said.append(country)
    for field, label in (("expected_shipment_date", "선적"), ("expected_payment_date", "결제")):
        day = _day_of(heard.get(field))
        if day:
            said.append(f"{day} {label}")
    if not said:
        return None

    line = f"{' · '.join(said)}로 읽었습니다."
    # The term is not a seventh thing that was heard — it is the first thing
    # this product worked out, and saying it here is what shows the difference
    # between a form that echoes and a tool that read.
    days = _days_between(
        heard.get("expected_shipment_date"), heard.get("expected_payment_date")
    )
    if days is not None and days > 0:
        line += f" 선적일과 결제일 사이는 {days}일입니다."
    return line


#: What a request field is called once a rule is reading it.
#:
#: The screen sends what it set — `company_size`, or the trade slot a question
#: asked for — and a check names the fact a rule wanted. Mostly the two are the
#: same word; where they are not, it is because the answer is an input to the
#: fact rather than the fact itself. 선적일 is the clear case: nobody is asked
#: for a payment term, they are asked when they ship, and the term is worked
#: out from that and the settlement date.
_ANSWER_CLOSES = {
    "company_size": "company.size",
    "credit_issue_free": "company.credit_issue_free",
    "expected_shipment_date": "trade.payment_term_days",
}


def closed(result: dict[str, Any], answered: list[str] | None) -> str | None:
    """Which conditions the answer just given got past.

    Five questions in a row, each arriving with no sign that the last one did
    anything. The rules were closing conditions on every turn and the screen
    reported none of it — so answering felt like filling a form that kept
    growing, when in fact each answer was settling named conditions on named
    products.

    Causality is not observable here and is not claimed. What is said is that
    a condition the reader was asked about is now passed, which is true and is
    the part they cannot see for themselves. A condition that came back failed
    is left to the judgement below to report; announcing it here would put the
    bad news in the sentence about progress.
    """
    wanted = {_ANSWER_CLOSES.get(field, field) for field in answered or []}
    if not wanted:
        return None

    # By condition rather than by product: one answer clears the same condition
    # on several products at once, and naming the condition three times is the
    # duplication `_one_per_rule` exists to stop, arriving from a new direction.
    by_condition: dict[str, list[str]] = {}
    for candidate in _one_per_rule(
        result.get("support_candidates") or [], prefer=_weaker
    ):
        title = candidate.get("title") or ""
        for check in candidate.get("checks") or []:
            if check.get("field") not in wanted or check.get("status") != "passed":
                continue
            titles = by_condition.setdefault(check["description"], [])
            if title and title not in titles:
                titles.append(title)
    if not by_condition:
        return None

    # Conditions first, then where they were. Naming the products beside each
    # condition put `·` to work as both separators at once — 「중소·중견기업」 —
    # K-SURE 일반형 수출 환변동보험 · K-SURE 수출신용보증(선적전) · 「공식 안내
    # …」 — and nothing in the line said which dot meant which.
    conditions = _joined([f"「{name}」" for name in by_condition])
    products = list(dict.fromkeys(title for titles in by_condition.values() for title in titles))
    # One product is worth naming; several are a count, because the blocks
    # directly below list every one of them beside the conditions it holds.
    # This line's work is momentum, not the record.
    where = products[0] if len(products) == 1 else f"제도 {len(products)}건"
    return (
        f"방금 답해 주신 것으로 {conditions}{_particle(conditions, SUBJECT)}"
        f" 지나갔습니다 — {where}."
    )


def basis(result: dict[str, Any]) -> str | None:
    """What the loss figure is computed from, in one line.

    The summary sentence names an amount of won the company could lose, and it
    was the only claim on the screen with nothing under it. Every rule
    judgement could at least be opened; the largest number in the answer could
    not, so the one figure most likely to be repeated to a bank was the one
    least able to say where it came from.

    Three things produce it and all three are already in the response: the
    exposure it is measured on, the rate the scenario reached, and the window
    the volatility was estimated over. None of them is a new computation —
    this is a sentence about numbers that already exist, which is why it can be
    written here rather than by a worker.
    """
    market = result.get("market_scenario") or {}
    if not market.get("adverse_rate"):
        return None

    parts: list[str] = []
    net = ((result.get("cashflow_analysis") or {}).get("net_exposure") or [{}])[0]
    if net.get("amount") is not None:
        amount = _amount(net.get("amount"))
        parts.append(
            f"거래 순노출 {abs(amount):,.0f} {net.get('currency', 'USD')}"
            " = Σ수취 − Σ지급"
        )

    spot = market.get("spot_rate")
    adverse = market.get("adverse_rate")
    confidence = market.get("confidence_level")
    rate = f"불리 환율 {_amount(adverse):,.2f}원"
    if spot:
        rate += f" (현재 {_amount(spot):,.2f}원"
        # The interval is what makes the adverse rate a bound rather than a
        # prediction, and §5.2 refuses to produce one without it.
        if confidence:
            rate += f", 신뢰수준 {_amount(confidence) * 100:.0f}%"
        rate += ")"
    parts.append(rate)

    observed_from, observed_to = market.get("observed_from"), market.get("observed_to")
    if observed_from and observed_to:
        days = market.get("observation_days")
        window = f"관측 {observed_from} ~ {observed_to}"
        if days:
            window += f" ({days}영업일)"
        parts.append(window)

    return " · ".join(parts)


def grounded(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Every claim the answer makes, each carrying the evidence for itself.

    `support`, `compliance` and `actions` write the claims; `detail` writes the
    lists behind them. Both are correct and the screen could not join them: the
    sentences come out settled-first while the rows come out in rule order, so
    the third sentence and the third row were about different products. What
    the screen did instead was print all the sentences as one paragraph and put
    all the rows in a fold underneath — five assertions in a block, and the
    grounds for any one of them behind a click and a search.

    Reading it meant holding a claim in your head, opening the fold, finding
    which row belonged to it, and coming back. The evidence was present and
    unusable, which is a worse failure than absent: the product looks like it
    is showing its work while making the work unreadable.

    So the pairing is made here, where both halves are built from the same
    candidate in the same pass. There is no key to join on and nothing to keep
    in step — a claim without its grounds cannot be constructed.

    The claims are not re-worded. This is the same text `support` and the rest
    already produce, so a reader comparing the summary against these blocks
    sees the same sentences, and the synthesis guard keeps checking the same
    strings it always has.
    """
    blocks: list[dict[str, Any]] = []

    for candidate in _one_per_rule(
        result.get("support_candidates") or [], prefer=_weaker
    ):
        checks = candidate.get("checks") or []
        met = [c["description"] for c in checks if c.get("status") == "passed"]
        wanted = [c["description"] for c in checks if c.get("status") == "uncertain"]
        claim = _support_claim(candidate, met, wanted)
        if not claim:
            continue
        theirs, ours = _split_wanted(checks)
        blocks.append(
            {
                "kind": "support",
                "claim": claim,
                # `settled` is what the chip and the ordering both read. A
                # product still short of a fact is not a weaker yes.
                "settled": candidate.get("status") != _SETTLED,
                "met": met,
                # Kept apart on the screen too. Under one 「필요」 label they
                # read as one list of things the reader has to go and find out,
                # and one of them is ours.
                "wanted": theirs,
                "ours": ours,
            }
        )

    # Ordered the way `support` orders its sentences — decided first, open
    # after. The reader's question is 「받을 수 있나요」 and an answer that
    # opens with what is still unknown answers a different one.
    blocks.sort(key=lambda block: not block["settled"])

    for line in compliance(result):
        # §5.5's paragraph is already one claim per sentence and its grounds
        # are inside the sentence — the branch condition *is* the evidence.
        # Splitting it into met/wanted would be inventing a structure the
        # rulepack does not have.
        blocks.append({"kind": "compliance", "claim": line, "met": [], "wanted": []})

    for action in _one_per_errand(result):
        authority = AUTHORITY_NAME.get(action.get("authority"), action.get("authority"))
        documents = action.get("required_documents") or []
        blocks.append(
            {
                "kind": "action",
                "claim": (
                    f"다음은 {authority} "
                    f"{ACTION_NAME.get(action.get('action'), '상담 및 신청')}입니다."
                ),
                "met": [],
                # The documents are the grounds for 「필요서류는 6건입니다」.
                # A count with the list one click away is the shape this whole
                # function exists to undo.
                "wanted": documents,
            }
        )

    return blocks


def _split_wanted(checks: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """The open conditions, split by who is supposed to close them.

    `asking.ASKABLE` decides which facts this product puts to a company, and
    the set is deliberately small — 국별인수방침 인수제한국 여부 is not in it,
    because asking a company whether its buyer's country is restricted is
    asking them to make our judgement and their answer would be evidence of
    nothing.

    That decision was being contradicted one screen later. The sentence said
    「국별인수방침 인수제한국 소재가 아님을 알려주시면 판정합니다」 — demanding
    the very fact the intake refuses to ask for, and leaving the reader waiting
    on a question that never arrives.
    """
    from tradeflow.runtime.asking import ASKABLE

    # A check has to *name* a field before this can say the field is not one we
    # ask about. Routing an unnamed condition to our side would tell the reader
    # to sit and wait for a lookup nobody is doing — the failure that is
    # hardest to notice, because the screen looks like it is working on it.
    theirs, ours = [], []
    for check in checks:
        if check.get("status") != "uncertain":
            continue
        field = check.get("field")
        (ours if field and field not in ASKABLE else theirs).append(
            check["description"]
        )
    return theirs, ours


def _support_claim(candidate: dict[str, Any], met: list[str], wanted: list[str]) -> str:
    """One product's verdict, worded exactly as `support` words it."""
    title = candidate.get("title") or ""
    if candidate.get("status") != _SETTLED:
        line = f"{title}{_particle(title, TOPIC)} 조건을 충족합니다."
        if met:
            line += f" 확인한 조건은 {len(met)}가지입니다."
        if candidate.get("status") == "expert_confirmation_required":
            line += " 초안 규칙이라 공식 확인을 받으셔야 합니다."
        return line
    if not wanted:
        return ""
    theirs, ours = _split_wanted(candidate.get("checks") or [])
    line = f"{title}{_particle(title, TOPIC)} 아직 판정하지 못했습니다."
    if theirs:
        listed = _some(theirs)
        line += f" {listed}{_particle(listed, OBJECT)} 알려주시면 판정합니다."
    if ours:
        listed = _some(ours)
        # Named, not hidden. A condition nobody is going to be asked about is
        # still a condition the judgement is waiting on, and a reader who is
        # not told will read the silence as the rule having passed.
        line += (
            f" {listed}{_particle(listed, SUBJECT)} 남아 있는데, 이건 여쭙지 않고"
            " 저희가 확인할 항목입니다."
        )
    return line


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
