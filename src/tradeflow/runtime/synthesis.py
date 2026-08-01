"""The sentences a language model may write, and the conditions on them.

Two of them. §4.2[9] turns finished figures into an explanation, and §4.2[1]
turns a list of missing slots into a question. Neither decides anything: the
figures are already computed when the first runs, and *which* slots are missing
is already decided when the second runs. The model supplies Korean, not
judgement.

That division is why this is safe at all, and it is enforced rather than
requested — see `check` below.

---

§4.2[9] 응답 합성 — the one field a language model may write.

The spec gives this agent no tools and one strict rule:

> 도구가 산출한 수치를 그대로 인용한다. 재계산·반올림·근사 표현을 금지한다.

A prompt asking for that is a request. This module makes it a condition. The
model is handed a list of figure strings that the deterministic tools produced,
and its sentence is checked twice. Every run of digits it wrote must appear,
character for character, among those figures — a sentence that introduces `10만`
where the tools said `100,000` is rejected, because rounding is the failure this
rule names and the check cannot tell a helpful rounding from a wrong one. And
every number must still be wearing the unit it came with: quoting `100,000` and
calling it KRW passes any arithmetic check and has lost the meaning entirely.

Between those two, the model writes the sentence. Letting it only *pick*
pre-rendered phrases would close the same holes, but §4.2[9]'s responsibility is
"사용자 수준 설명 생성" — labels joined by dots are the card restated, not an
explanation.

A rejected sentence, an unreachable API and an absent key all end the same way:
`summary` stays empty and the screen falls back to the sentence it assembles
itself. Synthesis is the last step and it decorates figures that are already
decided, so losing it costs prose and never an answer.

That is also why this lives in `runtime` and not in `integration`, which
ADR-0003 keeps unreachable by import because it fetches facts that must be
snapshotted and dated. This fetches no facts. It is handed them.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass
from typing import Any

#: Pinned, not an alias. An alias resolves to a dated build today and to a
#: different one whenever Upstage ships — §6.2 asks that the same analysis
#: re-run produce the same packet, and a model that changes under a stable name
#: cannot be recorded honestly in `calculation_versions`.
#:
#: pro2 rather than pro3, on measurement. The same intake call, three runs each:
#:
#:   solar-pro3-260323   19.1 / 19.2 / 17.1 s
#:   solar-pro2-251215    0.8 / 0.7  / 0.6  s
#:   solar-mini-250422    0.4 / 0.5  / 0.4  s
#:
#: Twenty-five times, for a sentence of the same quality. A greeting took
#: seventeen seconds to answer, and the client's pacing has no way to hide
#: that — the trace budget is a floor on the wait, not a ceiling on it.
DEFAULT_MODEL = "solar-pro2-251215"
DEFAULT_BASE_URL = "https://api.upstage.ai/v1"

#: Deterministic decoding. Prose that changes between two identical analyses
#: would make the answer look recalculated when nothing moved.
TEMPERATURE = 0.0

#: How long an answer may wait on prose. Synthesis decorates figures that are
#: already decided, so a slow model must cost the sentence and not the answer —
#: past this the screen writes its own, which it can do instantly.
#:
#: This exists because the model choice above was wrong and nothing caught it.
#: A ceiling holds whoever is behind the endpoint next.
TIMEOUT_S = 6.0

#: Any signed run of digits, with the separators a formatted figure carries
#: inside it. The sign is part of the value: dropping `-` is not a paraphrase.
_DIGITS = re.compile(r"[+-]?\d[\d,.]*")

#: JSON Schema keywords Upstage's structured-output validator rejects outright.
#: `uniqueItems` was in both schemas and every call came back 400, so the model
#: contributed nothing at all — `summary` and `spoken` were empty on every
#: request while the screen quietly used its own sentences. Uniqueness is
#: cheaper to enforce here than to ask the server for.
#:
#: The lesson is the reason this file now has a live-call test: a schema that
#: cannot be validated without a key is a schema nobody validated.
UNSUPPORTED_SCHEMA_KEYWORDS = ("uniqueItems",)

SCHEMA = {
    "name": "summary",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sentence": {
                "type": "string",
                "description": "사용자에게 보여줄 한국어 설명. 두 문장 이내.",
            },
            "figures_used": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
                "description": "문장에 인용한 수치를, 제공된 문자열 그대로.",
            },
        },
        "required": ["sentence", "figures_used"],
        "additionalProperties": False,
    },
}

INSTRUCTION = """\
당신은 수출입 기업의 환위험 분석 결과를 설명합니다. 계산은 이미 끝났습니다.
당신의 일은 아래 「확정된 수치」를 사람의 문장으로 옮기는 것뿐입니다.

절대 규칙 — 숫자를 만들지 마세요:
- 아래 목록에 **문자열 그대로** 있는 숫자만 쓸 수 있습니다. 복사해서 붙이세요.
- 사칙연산을 하지 마세요. 두 수치를 곱하거나 더해 새 금액을 만들지 마세요.
- 반올림·근사를 하지 마세요. 100,000을 「10만」으로 바꾸는 것도 위반입니다.
- 사용자가 질문에 쓴 숫자도 그대로 인용하지 마세요. 목록의 수치를 쓰세요.
- 숫자에 붙은 단위를 바꾸지 마세요. USD를 KRW로 옮겨 쓸 수 없습니다.

금지되는 문장의 예 (전부 위반):
- "100,000 USD는 1466.3원 기준 146,630,000원입니다" → 곱셈을 했습니다
- "약 10만 달러의 노출이 있습니다" → 근사했습니다
- "순노출은 100,000 KRW입니다" → 단위를 바꿨습니다
- "3억 원 규모 수출이시군요" → 사용자가 쓴 숫자를 되받았습니다. 분석은 확정된
  수치로 돌았으니 목록의 값을 쓰세요

사용자가 걱정하는 것에 답하세요. 수치를 다시 읽어주는 것이 아니라,
그 수치가 그 사람에게 무엇을 뜻하는지 말하는 것입니다.

수출 기업이 "환율이 떨어질까 걱정"이라고 물었을 때:
- 나쁨: "순노출은 100,000 USD이고 그때 덜 받는 원화는 10,525,000 KRW입니다."
  → 카드에 있는 것을 다시 읽었습니다.
- 좋음: "받을 100,000 USD가 결제일까지 열려 있습니다. 불리한 쪽인 1361.05까지
  가면 그때 손에 들어오는 원화가 10,525,000 KRW 적어집니다."

수입 기업이 "환율이 오를까 걱정, 지금 환전할까요"라고 물었을 때:
- 나쁨: "순노출은 -100,000 USD입니다."  → 부호를 읽어줬을 뿐입니다.
- 좋음: "보내야 할 100,000 USD가 아직 환전되지 않았습니다. 불리한 쪽인
  1560.48까지 가면 결제에 9,418,000 KRW가 더 듭니다."

그 밖에:
- 환율을 예측하지 마세요. "~까지 가면"처럼 조건부로만 말하세요.
- 무엇을 하라고 지시하지 마세요. 판단은 아래 규칙 결과가 합니다.
- 목록을 옮겨 적지 마세요. 가장 중요한 수치 두세 개만 고르세요.
- 값이 0인 항목은 말하지 마세요. 자연헤지 0, 자금 공백 0을 나열하면 문장이
  카드의 복사본이 됩니다.
- 두 문장 이내. 짧을수록 좋습니다.
"""


@dataclass(frozen=True)
class Synthesis:
    """What came back, and whether it was allowed to be used."""

    sentence: str
    accepted: bool
    reason: str = ""

    @property
    def summary(self) -> str:
        return self.sentence if self.accepted else ""


#: A money amount as a person writes one: digits, an optional Korean magnitude,
#: and a currency. Matched as a whole so the unit goes with the number.
_SPOKEN_AMOUNT = re.compile(r"\d[\d,.]*\s*[억만천]?\s*(?:원|달러|불|USD|KRW)")


def redact(text: str) -> str:
    """The question with its numbers taken out, leaving ordinary Korean.

    An earlier version left `○○` where a number had been, and the model copied
    the marker into the answer — "○○억 원 규모 장비" reached the check and was
    rejected, so the scenario got no sentence at all. A placeholder that looks
    like content will be treated as content. What is left here is a phrase a
    person could have written, with nothing worth quoting.
    """
    return _DIGITS.sub("몇", _SPOKEN_AMOUNT.sub("일정 금액", text))


def digit_runs(text: str) -> set[str]:
    """Every number in the text, as it was written."""
    return {match.group().rstrip(".,") for match in _DIGITS.finditer(text)}


#: 원 and KRW are the same unit; so are 달러 and USD. A sentence that writes
#: `10,525,000원` where the figure says `10,525,000 KRW` has not changed
#: anything, and rejecting it would reject ordinary Korean.
_UNIT_WORDS = {
    "USD": "USD", "달러": "USD",
    "KRW": "KRW", "원": "KRW",
    "%": "%", "영업일": "영업일",
}

#: Adjacent means adjacent — at most one space. A wider window read the `원` in
#: "1361.05까지 가면 원화 수취액이" as that number's unit and rejected a correct
#: sentence.
_ADJACENT_UNIT = re.compile(r"\s?(USD|KRW|달러|원|%|영업일)")


def units_by_run(text: str) -> dict[str, set[str | None]]:
    """Which unit each number is wearing, if any."""
    found: dict[str, set[str | None]] = {}
    for match in _DIGITS.finditer(text):
        run = match.group().rstrip(".,")
        unit = _ADJACENT_UNIT.match(text, match.end())
        found.setdefault(run, set()).add(
            _UNIT_WORDS[unit.group(1)] if unit else None
        )
    return found


#: Words that belong to a rule's verdict, not to a description of figures.
#:
#: The digit and unit checks both pass "신고 의무가 없으므로 바로 송금하세요" —
#: it contains no numbers at all. §5.5 is explicit that a filing duty is never
#: cleared until the company states its trade structure, so a sentence that
#: clears it is the model overruling a worker that deliberately stopped. The
#: same goes for eligibility and for telling anyone what to do: those verdicts
#: are rendered from their own worker output, in their own sections.
#:
#: The synthesis agent describes what was measured. It does not decide, and it
#: does not instruct.
VERDICT_WORDS = (
    "신고", "의무", "면제", "불필요", "해당 없음",
    "자격", "지원", "보험", "보증", "승인",
    # Instructions, in the endings Korean uses for them. Enumerated, so this is
    # a net and not a proof — a form nobody listed will pass. What guarantees
    # the division is that verdicts are rendered from worker output elsewhere;
    # this only keeps the sentence from competing with them. `검토해 보세요`
    # got through the first list, which had `하세요` and not `보세요`.
    "하세요", "보세요", "하십시오", "하시기 바랍니다", "하시면 됩니다",
    "권장", "권해", "추천", "안전합니다", "문제없",
)

#: The marker `redact` leaves behind. It is an editing device for the prompt and
#: has no business in a sentence a person reads — the model copied it straight
#: through ("○○억 원 규모 장비") the first time the question carried a number.
REDACTION = "○○"


def verdicts(sentence: str) -> list[str]:
    """Claims in the sentence that only a rule may make.

    A greeting is dropped first: `안녕하세요` contains `하세요`, and the
    intake path opens with one. Asking someone for a date is instructing them,
    which is why this is checked on the answer and not on the question.
    """
    text = sentence.replace("안녕하세요", "")
    return [word for word in VERDICT_WORDS if word in text]


def check(sentence: str, figures: list[str]) -> str:
    """Empty if the sentence only quotes figures it was given, else the reason.

    Substring matching is not enough: `1,361.05` contains `05`, and a model that
    wrote `05영업일` would slip through. Comparing whole runs against whole runs
    is what makes "그대로 인용" mean what it says.
    """
    joined = " ".join(figures)
    invented = sorted(digit_runs(sentence) - digit_runs(joined))
    if invented:
        return "확정된 수치에 없는 숫자: " + ", ".join(invented)

    # A right number wearing the wrong unit is not a quotation. Checking digits
    # alone let `100,000 USD` be written as `100,000 KRW`, which no arithmetic
    # check can see — the digits are quoted exactly and the meaning is gone.
    allowed_units = units_by_run(joined)
    for run, worn in units_by_run(sentence).items():
        for unit in worn:
            allowed = allowed_units.get(run, set())
            if unit is None and allowed and None not in allowed:
                return f"단위가 누락된 수치: {run}"
            if unit is not None and unit not in allowed:
                return f"단위가 바뀐 수치: {run} {unit}"

    return ""


_CLAUSE_BREAK = re.compile(r"(?:이며|이고|하고|지만|,(?!\d)|\.(?!\d)|[!?;。])")


def _label_anchors(label: str) -> tuple[str, ...]:
    shortened = re.sub(r"^(?:그때|현재)\s+", "", label).strip()
    shortened = re.sub(r"\s+(?:금액|차이)$", "", shortened).strip()
    return tuple(dict.fromkeys(item for item in (label.strip(), shortened) if item))


def _number_clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_BREAK.split(text) if digit_runs(part)]


def check_bound(sentence: str, figures: list[str]) -> str:
    """Verify that quoted numbers keep both their units and their labels.

    A digit-and-unit check alone accepts a semantic swap such as calling a KRW
    cashflow difference the net exposure. The deterministic label preceding
    each figure is therefore part of the quotation contract as well.
    """
    broken = check(sentence, figures)
    if broken:
        return broken

    bindings: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for figure in figures:
        label, separator, _ = figure.partition(":")
        if not separator:
            continue
        for run in digit_runs(figure):
            bindings.setdefault(run, []).append((figure, _label_anchors(label)))

    referenced: set[str] = set()
    for clause in _number_clauses(sentence):
        for run in digit_runs(clause):
            candidates = bindings.get(run, [])
            matched = [
                figure
                for figure, anchors in candidates
                if any(anchor in clause for anchor in anchors)
            ]
            if not matched:
                return f"의미가 바뀌거나 라벨이 누락된 수치: {run}"
            referenced.update(matched)

    unused = [figure for figure in figures if figure not in referenced]
    if unused:
        return "사용했다고 표시했지만 문장에 결합되지 않은 수치: " + ", ".join(unused)
    return ""


def figures(result: dict[str, Any]) -> list[str]:
    """The tools' own numbers, formatted once, in the words they belong to.

    §4.2[9] asks that a figure be shown with its unit, its reference rate and
    its reference moment. Doing that here rather than in the prompt means the
    model never sees a bare number it might attach to the wrong thing, and the
    strings it is allowed to quote are exactly the strings a reader will see.

    Thousands separators are added here too, so `100,000` is the only spelling
    in play. Handing over `100000` and rendering `100,000` would make the check
    reject the model for writing what the screen shows.
    """
    written: list[str] = []

    def money(value: Any) -> str:
        try:
            return f"{int(str(value)):,}"
        except (TypeError, ValueError):
            return str(value)

    cash = result.get("cashflow_analysis") or {}
    for key, label in (
        ("net_exposure", "순노출"),
        ("natural_hedge_amount", "자연헤지 금액"),
        ("maturity_matched_amount", "만기가 겹치는 금액"),
    ):
        for entry in cash.get(key) or []:
            written.append(f"{label}: {money(entry.get('amount'))} {entry.get('currency')}")
    for entry in cash.get("funding_gap") or []:
        written.append(f"자금 공백: {money(entry.get('peak_amount'))} {entry.get('currency')}")

    market = result.get("market_scenario") or {}
    if market:
        unit = market.get("unit", "KRW per USD")
        written.append(f"현재 환율: {market.get('spot_rate')} ({unit}, 한국은행 매매기준율 {market.get('observed_to')} 기준)")
        written.append(f"불리한 쪽 환율: {market.get('adverse_rate')} ({unit}, 신뢰수준 {market.get('confidence_level')})")
        # Whose money moves, and which way. The label used to say 수취액
        # whatever the trade was, so an import — where a rising rate means
        # paying more — was told its receipts had fallen. The company is not
        # receiving anything; it is paying, and the sentence said the opposite
        # of what happened to it.
        net = ((cash.get("net_exposure") or [{}])[0]).get("amount")
        try:
            receiving = Decimal(str(net)) > 0
        except (InvalidOperation, TypeError):
            receiving = None
        label = (
            "그때 덜 받는 원화" if receiving
            else "그때 더 내는 원화" if receiving is False
            else "그때 원화 현금흐름 차이"
        )
        written.append(
            f"{label}: {money(market.get('adverse_cashflow_amount'))} KRW"
        )
        written.append(
            f"관측 조건: 최근 {market.get('observation_days')}영업일, "
            f"잔여 {market.get('horizon_business_days')}영업일, 드리프트 {market.get('drift')}"
        )

    hedge = result.get("hedge_analysis") or {}
    if hedge:
        written.append(f"손익분기 환율: {hedge.get('breakeven_rate')} (KRW per USD)")
        written.append(f"최소 헤지비율: {hedge.get('optimal_ratio')}")

    return written


def deterministic_summary(result: dict[str, Any]) -> str:
    """A non-empty, non-judgemental answer assembled from tool output.

    LLM synthesis is optional decoration. API clients must still receive an
    answer when the key is absent, the network fails, or the generated prose
    is rejected. Values are copied from the response contract and only given
    thousands separators; no eligibility verdict or new arithmetic is added.
    """

    def money(value: Any) -> str:
        try:
            return f"{int(str(value)):,}"
        except (TypeError, ValueError):
            return str(value)

    cash = result.get("cashflow_analysis") or {}
    gaps = cash.get("funding_gap") or []
    exposures = cash.get("net_exposure") or []
    parts: list[str] = []
    if gaps:
        gap = gaps[0]
        parts.append(
            f"최대 자금 공백은 {money(gap.get('peak_amount'))} "
            f"{gap.get('currency')}입니다."
        )
    if exposures:
        exposure = exposures[0]
        parts.append(
            f"결제일을 반영한 순노출은 {money(exposure.get('amount'))} "
            f"{exposure.get('currency')}입니다."
        )
    if not parts:
        return "분석 결과를 아래 항목별로 확인해 주세요."
    return " ".join(parts)


def pointer(result: dict[str, Any]) -> str:
    """What else this answer holds, counted rather than judged.

    §4.2[9]'s sentence is given `figures()` and nothing else, so it cannot
    mention that three support candidates were decided — and it should not be
    able to. A model that could say "지원제도 후보가 있습니다" could also say
    "자격이 됩니다", and the whole division rests on it not being able to.

    So the pointer is written here. Counts only: how many were judged, how many
    are still short of a fact, how many actions came out. Every verdict stays
    where it is rendered, from its own worker's output, with its own evidence.

    Without this the screen answered a question about 지원제도 with a sentence
    about exchange rates and left the judgement folded away underneath.
    """
    skipped = (result.get("workers") or {}).get("skipped") or {}
    parts: list[str] = []

    candidates = result.get("support_candidates") or []
    if "support" not in skipped and candidates:
        short = sum(
            1 for item in candidates if item.get("status") == "insufficient_information"
        )
        piece = f"지원제도 후보 {len(candidates) - short}건"
        if short:
            piece += f" · 정보 부족 {short}건"
        parts.append(piece)

    if "compliance" not in skipped:
        obligations = result.get("filing_obligations") or []
        parts.append(
            f"신고 검토 {len(obligations)}건" if obligations else "신고 검토 결과"
        )

    actions = result.get("next_actions") or []
    if actions:
        parts.append(f"다음 행동 {len(actions)}건")

    # Joined with a dash rather than a particle: the last item changes every
    # time, and `을(를)` is what a template writes when it does not know the
    # word it is joining.
    return " · ".join(parts) + " — 아래에 정리했습니다." if parts else ""


INTAKE_INSTRUCTION = """\
당신은 수출입 기업을 돕습니다. 아직 판단에 필요한 정보가 부족한 상태이고,
무엇이 부족한지는 이미 정해져 있습니다. 당신의 일은 그것을 자연스러운
한국어 한두 문장으로 옮기는 것뿐입니다.

규칙:
- 사용자가 물은 주제를 받아 말하세요. 지원제도를 물었으면 지원제도를 보려면
  무엇이 필요한지 말하는 것이지, 「환위험 분석을 도와드리겠습니다」가
  아닙니다. 묻지 않은 것의 이름을 대지 마세요.
- 「물어야 할 것」을 늘리거나 줄이지 마세요. 목록에 있는 것만 물으세요.
- 「이미 파악한 것」은 다시 묻지 마세요.
- 숫자를 만들지 마세요. 이미 파악한 값만 그대로 쓸 수 있습니다.
- 계산 결과를 추측하거나 언급하지 마세요. 아직 계산하지 않았습니다.
- 사용자가 인사를 했다면 짧게 받고 본론으로 가세요.
- 한두 문장. 심문이 아니라 안내처럼.
"""

INTAKE_SCHEMA = {
    "name": "intake",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "sentence": {"type": "string", "description": "사용자에게 보여줄 한두 문장."},
            "asked_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "이 문장이 실제로 물은 항목의 이름. 목록에서 고르세요.",
            },
        },
        "required": ["sentence", "asked_fields"],
        "additionalProperties": False,
    },
}

#: §4.2[2]'s section names, in the words a person uses for them.
SUBJECT_NAME = {
    "exposure": "환노출",
    "market_scenario": "환율 시나리오",
    "hedge": "헤지",
    "support": "지원제도",
    "compliance": "신고의무",
}

FIELD_WORDS = {
    "amount": "거래 금액 (달러)",
    "expected_payment_date": "대금을 주고받기로 한 날짜",
    "direction": "수출인지 수입인지",
}


class Synthesizer:
    """The §4.2[9] agent, or nothing at all when there is no key.

    Constructing this without a key is not an error — the product answers
    without prose, and refusing to start because a decorative step is
    unavailable would make an optional dependency a required one.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("UPSTAGE_API_KEY")
        self.base_url = base_url or os.environ.get("UPSTAGE_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.environ.get("UPSTAGE_MODEL", DEFAULT_MODEL)
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _open(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def write(self, figures: list[str], *, question: str | None = None) -> Synthesis:
        """One sentence about these figures, or a refusal with its reason."""
        if not self.available:
            return Synthesis("", False, "UPSTAGE_API_KEY가 없습니다")
        if not figures:
            return Synthesis("", False, "인용할 수치가 없습니다")

        # The question is passed for tone, not for figures. Asking the model not
        # to quote the user's numbers did not work — "3억 원 규모" came back
        # every time and failed the check, so the answer fell through to the
        # deterministic sentence. Redacting them removes the temptation instead
        # of appealing against it: what is left is the concern, which is the
        # only part of the question this path needs.
        #
        # `ask_for` keeps the digits. Asking may repeat what the user said;
        # answering must report what the tools produced.
        asked = f"\n\n사용자가 물은 내용: {redact(question)}" if question else ""
        prompt = (
            f"{INSTRUCTION}\n확정된 수치:\n"
            + "\n".join(f"- {figure}" for figure in figures)
            + asked
        )
        schema = json.loads(json.dumps(SCHEMA))
        schema["schema"]["properties"]["figures_used"]["items"]["enum"] = figures
        try:
            completion = self._open().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": schema},
                temperature=TEMPERATURE,
                max_tokens=400,
                timeout=TIMEOUT_S,
            )
            written = json.loads(completion.choices[0].message.content or "{}")
        except Exception as failure:  # noqa: BLE001 — any failure is the same failure
            # The network, the key, the schema, the JSON. None of them change
            # what happens next: the screen writes the sentence itself.
            return Synthesis("", False, f"합성 호출 실패: {type(failure).__name__}")

        sentence = str(written.get("sentence", "")).strip()
        if not sentence:
            return Synthesis("", False, "빈 문장")

        if REDACTION in sentence:
            return Synthesis(sentence, False, "편집 표시가 문장에 남았습니다")

        # A semantic verdict is more dangerous than a malformed quotation, so
        # report and reject it before checking which figures the model claimed.
        claimed_verdicts = verdicts(sentence)
        if claimed_verdicts:
            return Synthesis(
                sentence,
                False,
                "규칙이 내려야 할 판단: " + ", ".join(claimed_verdicts),
            )

        used = written.get("figures_used")
        if (
            not isinstance(used, list)
            or not used
            or len(used) > 3
            or len(set(used)) != len(used)
            or any(not isinstance(item, str) or item not in figures for item in used)
        ):
            return Synthesis(sentence, False, "사용 수치 목록이 허용된 값과 일치하지 않습니다")

        broken = check_bound(sentence, used)
        if broken:
            return Synthesis(sentence, False, broken)
        return Synthesis(sentence, True)

    def ask_for(
        self,
        missing: list[str],
        *,
        understood: dict[str, Any] | None = None,
        question: str | None = None,
        subjects: list[str] | None = None,
    ) -> Synthesis:
        """§4.2[1]: say what is still needed, in words rather than in a list.

        `subjects` is what §4.2[2] read out of the sentence. Without it every
        question named 환위험 분석 whatever had been asked — a company asking
        about 정책자금 was told which inputs the exchange-rate analysis wanted,
        by name, which is the funnel telling the user what the product is
        instead of answering them.

        The slots come in already chosen — §4.2[1] fixes both the priority
        (`amount` → `expected_payment_date` → `direction`) and the cap of three,
        and reading a sentence for values is `read_utterance`'s job, not this
        one's. Handing that decision to a model would make what the product asks
        for vary between two identical situations.

        This is the path a session almost always starts on. The spec says so:
        "대상 사용자는 자신의 환노출액을 인지하지 못하는 집단이므로, 대부분의
        세션이 불완전한 입력으로 시작한다." Wiring the model only into the
        finished answer left the most-seen screen reciting fixed strings at
        someone who had said hello.
        """
        if not self.available or not missing:
            return Synthesis("", False, "합성할 수 없습니다")

        known = understood or {}
        wanted = [FIELD_WORDS.get(field, field) for field in missing]
        prompt = (
            f"{INTAKE_INSTRUCTION}\n물어야 할 것:\n"
            + "\n".join(f"- {word}" for word in wanted)
            + (
                "\n\n이미 파악한 것:\n"
                + "\n".join(f"- {key}: {value}" for key, value in known.items())
                if known
                else "\n\n이미 파악한 것: 없음"
            )
            + (
                "\n\n사용자가 물은 주제: "
                + " · ".join(SUBJECT_NAME.get(s, s) for s in subjects)
                if subjects
                else ""
            )
            + (f"\n\n사용자가 방금 한 말: {question}" if question else "")
        )
        schema = json.loads(json.dumps(INTAKE_SCHEMA))
        schema["schema"]["properties"]["asked_fields"]["items"]["enum"] = missing
        schema["schema"]["properties"]["asked_fields"]["minItems"] = len(missing)
        schema["schema"]["properties"]["asked_fields"]["maxItems"] = len(missing)
        try:
            completion = self._open().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": schema},
                temperature=TEMPERATURE,
                max_tokens=300,
                timeout=TIMEOUT_S,
            )
            written = json.loads(completion.choices[0].message.content or "{}")
        except Exception as failure:  # noqa: BLE001
            return Synthesis("", False, f"되묻기 합성 실패: {type(failure).__name__}")

        sentence = str(written.get("sentence", "")).strip()
        if not sentence:
            return Synthesis("", False, "빈 문장")

        # Asking may repeat; answering must report. What the user themselves
        # wrote is quotable here — echoing "10만 달러" back to the person who
        # just said it is confirmation, not the rounding §4.2[9] forbids. A
        # third number, belonging to neither the user nor the parse, is still
        # the model filling a slot instead of asking for it.
        allowed = [f"{key}: {value}" for key, value in known.items()]
        if question:
            allowed.append(question)
        broken = check(sentence, allowed)
        if broken:
            return Synthesis(sentence, False, broken)

        # Every slot the reader found missing, and no others. A model that
        # dropped one would leave the user answering two questions and waiting
        # on a third nobody asked; one that added a field is off the list §4.2[1]
        # fixed. Self-reported, so it catches wandering rather than lying — the
        # guarantee that matters is upstream, where `missing` was decided.
        claimed = [str(field) for field in written.get("asked_fields", [])]
        if set(claimed) != set(missing) or len(claimed) != len(missing):
            return Synthesis(sentence, False, "필수 질문 목록이 일치하지 않습니다")
        return Synthesis(sentence, True)
