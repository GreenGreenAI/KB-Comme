"""§4.2[9] 응답 합성 — the one field a language model may write.

The spec gives this agent no tools and one strict rule:

> 도구가 산출한 수치를 그대로 인용한다. 재계산·반올림·근사 표현을 금지한다.

A prompt asking for that is a request. This module makes it a condition. The
model is handed a list of figure strings that the deterministic tools produced,
and its sentence is then checked digit by digit: every run of digits it wrote
must appear, character for character, among those figures. A sentence that
introduces `10만` where the tools said `100,000` is rejected — not because the
two disagree, but because rounding is the failure this rule names, and the
check cannot tell a helpful rounding from a wrong one.

A rejected sentence, an unreachable API and an absent key all end the same way:
`summary` stays empty and the screen falls back to the sentence it assembles
itself. Synthesis is the last step and it decorates figures that are already
decided, so losing it costs prose and never an answer.

That is also why this lives in `runtime` and not in `integration`, which
ADR-0003 keeps unreachable by import because it fetches facts that must be
snapshotted and dated. This fetches no facts. It is handed them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

#: Pinned, not the `solar-pro3` alias. The alias resolves to a dated build today
#: and to a different one whenever Upstage ships — §6.2 asks that the same
#: analysis re-run produce the same packet, and a model that changes under a
#: stable name cannot be recorded honestly in `calculation_versions`.
DEFAULT_MODEL = "solar-pro3-260323"
DEFAULT_BASE_URL = "https://api.upstage.ai/v1"

#: Deterministic decoding. Prose that changes between two identical analyses
#: would make the answer look recalculated when nothing moved.
TEMPERATURE = 0.0

#: Any run of digits, with the separators a formatted figure carries inside it.
#: Trailing separators are trimmed so a figure at the end of a clause matches.
_DIGITS = re.compile(r"\d[\d,.]*")

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

금지되는 문장의 예 (전부 위반):
- "100,000 USD는 1466.3원 기준 146,630,000원입니다" → 곱셈을 했습니다
- "약 10만 달러의 노출이 있습니다" → 근사했습니다
- "1,466원 수준입니다" → 반올림했습니다

좋은 문장의 예:
- "순노출은 100,000 USD입니다. 불리한 쪽 환율 1361.05까지 가면 원화 수취액이
  10,525,000 KRW 줄어듭니다."

그 밖에:
- 환율을 예측하지 마세요. "~까지 가면"처럼 조건부로만 말하세요.
- 두 문장 이내로, 담당자가 무엇을 알아야 하는지 말하세요.
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


def digit_runs(text: str) -> set[str]:
    """Every number in the text, as it was written."""
    return {match.group().rstrip(".,") for match in _DIGITS.finditer(text)}


def check(sentence: str, figures: list[str]) -> str:
    """Empty if the sentence only quotes figures it was given, else the reason.

    Substring matching is not enough: `1,361.05` contains `05`, and a model that
    wrote `05영업일` would slip through. Comparing whole runs against whole runs
    is what makes "그대로 인용" mean what it says.
    """
    allowed = digit_runs(" ".join(figures))
    invented = sorted(digit_runs(sentence) - allowed)
    if invented:
        return "확정된 수치에 없는 숫자: " + ", ".join(invented)
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
        written.append(
            f"그때 원화 수취액 차이: {money(market.get('adverse_cashflow_amount'))} KRW "
            f"({'감소' if market.get('adverse_cashflow_direction') == 'decrease' else '증가'})"
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

        # The question is passed for tone, not for figures — it usually contains
        # the user's own spelling of the amount ("10만 달러"), and the first
        # version of this quoted it straight back and failed the check.
        asked = (
            f"\n\n사용자가 물은 내용(숫자는 인용하지 말 것): {question}"
            if question
            else ""
        )
        prompt = (
            f"{INSTRUCTION}\n확정된 수치:\n"
            + "\n".join(f"- {figure}" for figure in figures)
            + asked
        )
        try:
            completion = self._open().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": SCHEMA},
                temperature=TEMPERATURE,
                max_tokens=400,
            )
            import json

            written = json.loads(completion.choices[0].message.content or "{}")
        except Exception as failure:  # noqa: BLE001 — any failure is the same failure
            # The network, the key, the schema, the JSON. None of them change
            # what happens next: the screen writes the sentence itself.
            return Synthesis("", False, f"합성 호출 실패: {type(failure).__name__}")

        sentence = str(written.get("sentence", "")).strip()
        if not sentence:
            return Synthesis("", False, "빈 문장")

        broken = check(sentence, figures)
        if broken:
            return Synthesis(sentence, False, broken)
        return Synthesis(sentence, True)
