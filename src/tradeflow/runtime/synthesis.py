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
model may select up to three complete figure strings that the deterministic
tools produced. Code validates exact membership and renders those strings;
model-authored prose never reaches the user. A sign, unit, label or meaning
therefore cannot be detached from its value.

A rejected selection, an unreachable API and an absent key all end the same way:
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
            "figures_used": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 3,
                "description": "사용자에게 우선 보여줄 확정 문구를 제공된 문자열 그대로.",
            },
        },
        "required": ["figures_used"],
        "additionalProperties": False,
    },
}

INSTRUCTION = """\
당신은 수출입 기업의 환위험 분석 결과를 설명합니다. 계산은 이미 끝났습니다.
당신의 일은 아래 「확정된 문구」 중 사용자에게 우선 보여줄 항목을 최대 3개
선택하는 것뿐입니다. 문구를 다시 쓰거나 새로운 문장을 만들지 마세요.

반드시 목록의 문자열을 그대로 `figures_used`에 넣으세요. 숫자·부호·단위·라벨을
바꾸거나 목록 밖의 결론을 추가할 수 없습니다.
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


def _render_figures(selected: list[str]) -> str:
    """Render only tool-owned phrases; model-authored prose never reaches UI."""
    return " · ".join(item.rstrip(" .") for item in selected) + "."


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


INTAKE_INSTRUCTION = """\
당신은 수출입 기업의 환위험 분석을 돕습니다. 아직 계산에 필요한 정보가
부족한 상태이고, 무엇이 부족한지는 이미 정해져 있습니다. 당신의 일은 그것을
자연스러운 한국어로 옮기는 것뿐입니다.

규칙:
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
            "acknowledgement": {
                "type": "string",
                "enum": ["", "안녕하세요.", "확인했습니다."],
                "description": "질문 앞에 붙일 짧은 응답.",
            },
            "asked_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "이 문장이 실제로 물은 항목의 이름. 목록에서 고르세요.",
            },
        },
        "required": ["acknowledgement", "asked_fields"],
        "additionalProperties": False,
    },
}

FIELD_WORDS = {
    "amount": "거래 금액 (달러)",
    "expected_payment_date": "대금을 주고받기로 한 날짜",
    "direction": "수출인지 수입인지",
}


def _render_questions(
    missing: list[str],
    *,
    acknowledgement: str = "",
    understood: dict[str, Any] | None = None,
) -> str:
    """Render the complete deterministic question list selected upstream."""
    words = [FIELD_WORDS.get(field, field) for field in missing]
    if len(words) == 1:
        request = words[0]
    else:
        request = ", ".join(words[:-1]) + f", {words[-1]}"
    prefix = acknowledgement.strip()
    if not prefix and understood:
        prefix = "확인했습니다."
    return f"{prefix + ' ' if prefix else ''}{request}를 알려주세요."


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
        schema = json.loads(json.dumps(SCHEMA))
        schema["schema"]["properties"]["figures_used"]["items"]["enum"] = figures
        try:
            completion = self._open().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema", "json_schema": schema},
                temperature=TEMPERATURE,
                max_tokens=400,
            )
            written = json.loads(completion.choices[0].message.content or "{}")
        except Exception as failure:  # noqa: BLE001 — any failure is the same failure
            # The network, the key, the schema, the JSON. None of them change
            # what happens next: the screen writes the sentence itself.
            return Synthesis("", False, f"합성 호출 실패: {type(failure).__name__}")

        selected = written.get("figures_used")
        if (
            not isinstance(selected, list)
            or not selected
            or len(selected) > 3
            or len(set(selected)) != len(selected)
            or any(item not in figures for item in selected)
        ):
            return Synthesis("", False, "허용되지 않은 확정 문구 선택")
        return Synthesis(_render_figures(selected), True)

    def ask_for(
        self,
        missing: list[str],
        *,
        understood: dict[str, Any] | None = None,
        question: str | None = None,
    ) -> Synthesis:
        """§4.2[1]: say what is still needed, in words rather than in a list.

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
            )
            written = json.loads(completion.choices[0].message.content or "{}")
        except Exception as failure:  # noqa: BLE001
            return Synthesis("", False, f"되묻기 합성 실패: {type(failure).__name__}")

        claimed = {str(field) for field in written.get("asked_fields", [])}
        expected = set(missing)
        if claimed != expected or len(written.get("asked_fields", [])) != len(missing):
            return Synthesis("", False, "필수 질문 목록이 일치하지 않습니다")
        acknowledgement = str(written.get("acknowledgement", ""))
        if acknowledgement not in {"", "안녕하세요.", "확인했습니다."}:
            return Synthesis("", False, "허용되지 않은 응답 문구")
        return Synthesis(
            _render_questions(
                missing,
                acknowledgement=acknowledgement,
                understood=known,
            ),
            True,
        )
