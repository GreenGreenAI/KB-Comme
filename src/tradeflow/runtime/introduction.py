"""What this product does, in its own words, derived from what it holds.

"뭘 할 수 있어?" has an answer already sitting in the code: which calculations
are wired, which authorities have rules behind them. Writing that answer as a
paragraph would be the fourth place the same claim lives, and the first to go
stale — a marketing sentence outlives the rule it describes, and then the
product promises something it stopped doing.

So it is assembled. Adding a 수출입은행 rulepack changes this paragraph with
nobody editing it, exactly as it changes `coverage.statement`.
"""

from __future__ import annotations

from tradeflow.runtime import coverage

#: What the code computes, named the way the answer names it. This part is a
#: declaration — a worker's identifier does not say what a company gets from
#: it — but each line is one the response contract actually carries.
CALCULATIONS = (
    "수출입 거래의 순노출과 자금 공백",
    "한국은행 매매기준율 기준 환율 시나리오",
    "은행 선물환 호가를 받으면 헤지비율",
)


def _judgements() -> tuple[str, ...]:
    """The rule-backed judgements, named by the bodies that stand behind them.

    Read from the rulepacks. A section with no rules yet is left out rather
    than promised — `coverage` says what is missing, and this says what is
    there, from the same source.
    """
    said: list[str] = []
    for section, verb in (("support", "자격"), ("compliance", "신고 의무")):
        names = sorted(
            {
                coverage.INTENDED[section][authority]
                for authority in coverage.held(section)
                if authority in coverage.INTENDED[section]
            }
        )
        if names:
            said.append(f"{' · '.join(names)}의 {verb}")
    return tuple(said)


def paragraph() -> str:
    """One short answer to "뭘 할 수 있어?", with its own limits attached.

    The limits come from `coverage`, not from a second list here. A product
    that describes itself without them is answering a different question than
    the one asked.
    """
    lines = [
        "거래를 말씀해 주시면 이런 것을 계산하고 판정합니다.",
        "· " + "\n· ".join(CALCULATIONS),
    ]
    judgements = _judgements()
    if judgements:
        lines.append("· " + "\n· ".join(judgements))
    lines.append(
        "금액과 규정 판정은 코드가 하고, 근거로 쓴 출처와 기준일을 함께 "
        "보여드립니다. 환율을 예측하지는 않습니다."
    )
    limits = [coverage.statement(section) for section in ("support", "compliance")]
    stated = " ".join(line for line in limits if line)
    if stated:
        lines.append(stated)
    return "\n\n".join(lines)


def unread() -> str:
    """Said before the questions, when nothing in the sentence was recognised.

    Three questions arriving straight after a sentence nobody understood read
    as a demand. Saying so first turns the same three into a request — and it
    is what happened: neither the rules nor the model could place the sentence,
    and that is a fact about us, not about the person who wrote it.
    """
    return "말씀하신 내용을 제가 잘 이해하지 못했습니다. 아래를 알려주시면 계산을 시작하겠습니다."


def acknowledgement(*, holds_trade: bool = False) -> str:
    """A courteous reply when the model's own wording was refused.

    The refusal is about the phrasing, not about the reading: the sentence was
    judged small talk and only the words failed a check. Falling all the way
    back to the intake funnel would answer 「고마워요」 with a request for an
    amount, which is the thing this path exists to stop.
    """
    if holds_trade:
        return "네, 말씀 주시면 이어서 봐 드리겠습니다."
    return "네. 거래를 편하게 말씀해 주시면 계산을 시작하겠습니다."
