"""Reading the subject of a sentence with a model, on top of the keywords.

Setting out to let a model decide which tools to call turned up something
first: **intent has never selected a worker.** `plan_execution` records it and
says so — 「recorded and never subtracts from the plan」 — and which workers run
is decided by whether their inputs exist. Company facts open the eligibility
worker. A declared trade structure opens the filing worker. An operating profit
opens the hedge worker.

That decision is data sufficiency, and data sufficiency is not a judgement call.
Handing it to a model would trade a fact for an opinion.

What the keywords have actually been getting wrong all along is the *subject* —
and the subject decides the order the answer is read in, which section leads,
and what the product asks for next. Three times in one day: 「자금」 read as
exchange-rate exposure, 「상계」 not read at all, a greeting counted as a
half-described trade. Each was closed by editing a word list, which is a fix
that holds until the next sentence nobody thought of.

So the model reads the subject too, and the two readings are unioned. It may
add; it may not remove. That is `intent.py`'s rule — 의도는 답의 순서를 정하지
범위를 좁히지 않는다 — applied to the reader rather than to the answer: a model
that could drop 신고의무 from a question about 환율 would reopen exactly the
hole §2 describes, where the reader does not know what to ask about.

Failure is silence. No key, no network, a malformed reply — the keyword reading
stands on its own, as it did before this existed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tradeflow.runtime.synthesis import Synthesizer, TEMPERATURE, TIMEOUT_S, _seed
from tradeflow.tools.intent import DEFAULT_ORDER

logger = logging.getLogger("tradeflow.planner")

#: The subjects a sentence may be about. Taken from `intent.py` so the two
#: readings cannot disagree about what the vocabulary is.
SUBJECTS = tuple(DEFAULT_ORDER)

SUBJECT_HINT = {
    "exposure": "환노출 — 얼마를 받거나 내야 하는지, 자금이 언제 부족한지",
    "market_scenario": "환율 시나리오 — 환율이 어디까지 움직일 수 있는지",
    "hedge": "헤지 — 얼마나 헤지해야 하는지, 선물환을 걸지",
    "support": "지원제도 — 보험·보증·정책자금 등 받을 수 있는 제도",
    "compliance": "신고의무 — 외국환거래법상 신고·보고 대상인지",
}

INSTRUCTION = """\
사용자가 방금 한 말이 아래 주제 중 어떤 것에 대한 질문인지 고르세요.

주제:
{subjects}

규칙:
- 문장이 명시적으로 묻거나 분명히 함의하는 것만 고르세요.
- 확실하지 않으면 고르지 마세요. 빈 목록이 정답인 경우가 많습니다.
- 거래를 설명하기만 하고 아무것도 묻지 않았다면 빈 목록입니다.
- **사용자가 실제로 해결하려는 문제를 맨 앞에** 담으세요. 곁들여 떠오른
  주제는 뒤에 담거나 담지 마세요.

예:
- "거래처가 망하면 대금을 못 받을 텐데 방법이 있나요"
  → support 먼저. 걱정하는 것은 대금 회수이고 그것을 다루는 제도가 있습니다.
    신고의무는 이 문장이 묻는 것이 아닙니다.
- "지금 환전해 두는 게 나을까요" → hedge

당신이 고르는 것은 답의 순서일 뿐입니다. 고르지 않은 주제도 답에는 그대로
들어가므로, 무엇을 빼기 위해 고민하지 마세요.
"""

SCHEMA = {
    "name": "subjects",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "subjects": {
                "type": "array",
                "items": {"type": "string", "enum": list(SUBJECTS)},
                "maxItems": len(SUBJECTS),
            }
        },
        "required": ["subjects"],
        "additionalProperties": False,
    },
}


def widen(
    utterance: str | None,
    read: tuple[str, ...],
    *,
    synthesizer: Synthesizer | None = None,
    seed: str | None = None,
) -> tuple[str, ...]:
    """The keyword reading, plus whatever the model saw that it missed.

    The keyword reading keeps its order and its lead. The model appends; it
    never reorders and never removes, so the section that led before this
    existed still leads. A reading that could re-rank would make the answer
    arrive differently for two sentences the keywords read identically, and
    nothing on screen would say why.
    """
    if not utterance or not utterance.strip():
        return read

    agent = synthesizer or Synthesizer()
    if not agent.available:
        return read

    prompt = INSTRUCTION.format(
        subjects="\n".join(f"- {name}: {SUBJECT_HINT[name]}" for name in SUBJECTS)
    ) + f"\n사용자가 한 말: {utterance}"

    try:
        completion = agent._open().chat.completions.create(
            model=agent.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": SCHEMA},
            temperature=TEMPERATURE,
            seed=_seed(seed or utterance),
            max_tokens=120,
            timeout=TIMEOUT_S,
        )
        proposed: Any = json.loads(completion.choices[0].message.content or "{}")
    except Exception as failure:  # noqa: BLE001 — any failure leaves the keywords
        logger.info("주제 읽기 미채택: %s", type(failure).__name__)
        return read

    added = [
        name
        for name in (proposed.get("subjects") or [])
        if name in SUBJECTS and name not in read
    ]
    if added:
        logger.info("주제 넓힘: %s + %s", list(read), added)
    return (*read, *added)
