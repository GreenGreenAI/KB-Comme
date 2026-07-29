"""What each scenario needs, and how to tell whether the system produced it.

A capability is answered from the response contract, never from prose. Asking
"does our sentence look like the ideal answer" would score fluency, and the
cheapest way to raise that score is to invent — which is the one thing this
product refuses to do. Asking "did a rule actually decide this" scores the
thing that matters and cannot be gamed by writing better Korean.

A capability that is absent reports *why* it is absent, so the result reads as
a work list rather than as a grade.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: Authorities whose products scenario 2 asks for. None of them has a rulepack
#: yet — the registry carries K-SURE, the FX statutes and 기업마당 only.
POLICY_FINANCE = {"koreaexim", "kodit", "kibo", "kosmes", "sbc"}


@dataclass(frozen=True)
class Capability:
    name: str
    what: str
    #: Returns True when the response actually carries this judgement.
    present: Callable[[dict[str, Any]], bool]
    #: What would have to exist for it to be present. Empty when it already is.
    needs: str = ""


def _candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *(result.get("support_candidates") or []),
        *(result.get("excluded_candidates") or []),
    ]


def satisfied(item: dict[str, Any]) -> list[str]:
    """The conditions a rule actually evaluated, not the ones it went without.

    §5.4 reports both in `reasons`, and the first version of this counted
    `missing fact: counterparty.country_restricted` as evidence that country
    risk had been considered. It is the opposite — the rule said it does not
    know. A harness that reads a gap as a capability reports progress that did
    not happen, which is worse than not measuring at all.
    """
    return [
        reason
        for reason in item.get("reasons") or []
        if not reason.startswith("missing fact:")
    ]


def _authorities(result: dict[str, Any]) -> set[str]:
    found = set()
    for item in _candidates(result):
        outcome = item.get("outcome") or {}
        if outcome.get("authority"):
            found.add(outcome["authority"])
    for action in result.get("next_actions") or []:
        if action.get("authority"):
            found.add(action["authority"])
    return found


CAPABILITIES = (
    Capability(
        "exposure",
        "순노출·자금공백을 계산한다",
        lambda r: bool(r.get("cashflow_analysis")),
    ),
    Capability(
        "scenario",
        "조건부 환율 범위를 낸다",
        lambda r: bool(r.get("market_scenario")),
    ),
    Capability(
        "hedge_ratio",
        "손익분기 환율과 최소 헤지비율을 낸다",
        lambda r: bool(r.get("hedge_analysis")),
        needs="기준 영업이익·목표 손익 하한, 그리고 확인된 선물환 호가",
    ),
    Capability(
        "forward_quote",
        "무헤지·전액헤지 손익을 확인된 호가로 비교한다",
        # `instrument_candidates` names the measure the ratio rests on, and
        # `payoff_comparison` is what scenario 1 asks for by another name —
        # 무헤지·권장·100% 비교. Written against the response as it actually is;
        # the first version guessed a `quote_basis` key that does not exist.
        lambda r: bool((r.get("hedge_analysis") or {}).get("instrument_candidates"))
        and bool((r.get("hedge_analysis") or {}).get("payoff_comparison")),
        needs="은행이 확인해 준 선물환 호가. §5.3은 호가 없이 비율을 만들지 않는다",
    ),
    Capability(
        "support_ksure",
        "K-SURE 상품 자격을 판정한다",
        lambda r: "ksure" in _authorities(r),
    ),
    Capability(
        "support_policy_finance",
        "수출입은행·신보·기보·중진공 정책자금을 판정한다",
        lambda r: bool(POLICY_FINANCE & _authorities(r)),
        needs="해당 기관 출처와 룰팩. 현재 등록된 지원제도 출처는 K-SURE뿐",
    ),
    Capability(
        "compliance_filing",
        "외국환거래 신고 의무를 검토한다",
        lambda r: "compliance" not in (r.get("workers", {}).get("skipped") or {}),
        needs="상계·제3자 지급·상호계산·선수금 여부를 받을 요청 계약 필드",
    ),
    Capability(
        "country_risk",
        "상대국 인수방침을 판정에 반영한다",
        lambda r: any(
            reason.startswith("counterparty.country_restricted=")
            for item in _candidates(r)
            for reason in satisfied(item)
        ),
        needs=(
            "K-SURE 국별인수방침 스냅샷. 거래는 이미 상대국을 받고 판정 배선도 "
            "끝났으므로(agent/orchestrator._country_policy_assertions), 스냅샷이 "
            "생기면 코드 변경 없이 열린다. 지금 추출본에는 나라별 기록이 없다"
        ),
    ),
    Capability(
        "buyer_credit",
        "바이어 신용등급과 인수한도를 조회한다",
        lambda r: False,
        needs="외부 신용조사 조회. 우리가 대신 할 수 없고, 신청 절차 안내가 한계",
    ),
    Capability(
        "document_intake",
        "사용자가 올린 문서를 읽는다",
        lambda r: False,
        needs="파일 업로드 경로와 문서 파서. 지금 제품에 없는 계층",
    ),
    Capability(
        "lc_review",
        "UCP600 기준으로 신용장 조항을 검토한다",
        lambda r: False,
        needs="UCP600 출처와 룰팩. 출처 0, 규칙 0",
    ),
    Capability(
        "fx_deposit",
        "외화 예금·RP 금리를 비교한다",
        lambda r: False,
        needs="은행 금리 출처. 다만 이것은 금융상품 권유라 범위 결정이 먼저",
    ),
    Capability(
        "next_action",
        "다음에 무엇을 해야 하는지로 끝난다",
        lambda r: bool(r.get("next_actions")) or bool(r.get("required_inputs")),
    ),
    Capability(
        "evidence",
        "모든 판정이 출처를 달고 나온다",
        lambda r: bool(r.get("evidence"))
        and all(item.get("source_ids") for item in _candidates(r)),
    ),
)

BY_NAME = {capability.name: capability for capability in CAPABILITIES}
