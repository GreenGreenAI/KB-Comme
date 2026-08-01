"""Deterministic contracts for TradeFlow's decision-changing experience.

The language model may explain these records, but it does not choose the next
question or calculate a change.  Both projections are derived from the
verified analysis response so the same inputs and rule versions reproduce the
same experience.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


FIELD_QUESTIONS = {
    "opening_balance_usd": "현재 보유한 USD 외화잔액은 얼마인가요?",
    "financing.has_bank_consultation": (
        "취급 금융기관과 보증부 대출 가능성을 사전 상담했나요?"
    ),
    "financing.purpose": "이번 거래에서 검토할 금융 목적은 무엇인가요?",
    "trade.payment_term_days": "선적 또는 일람 후 결제일까지 며칠인가요?",
    "company.size": "기업 규모를 확인해 주세요.",
    "company.credit_issue_free": "현재 신용 제한 사유가 없는지 확인해 주세요.",
    "company.ksure_exporter_grade": "K-SURE 수출자 등급을 확인해 주세요.",
    "company.is_domestic": "대한민국 소재 기업인지 확인해 주세요.",
    "payment.is_netting": "이 거래가 상계 방식인지 확인해 주세요.",
    "payment.is_third_party": "제3자 지급 또는 수취 거래인지 확인해 주세요.",
    "payment.uses_mutual_account": "상호계산계정을 사용하는지 확인해 주세요.",
    "payment.uses_foreign_exchange_bank": (
        "외국환은행을 통해 지급하거나 수취하는지 확인해 주세요."
    ),
    "baseline_profit": "기준 영업이익을 입력해 주세요.",
    "profit_floor": "지키려는 손익 하한을 입력해 주세요.",
}

FIELD_IMPACTS = {
    "financing.has_bank_consultation": (
        "금융지원 후보 상태",
        "다음 행동",
    ),
    "financing.purpose": ("금융지원 후보 상태", "다음 행동"),
    "trade.payment_term_days": ("금융지원 후보 상태",),
    "company.size": ("금융지원 후보 상태",),
    "company.credit_issue_free": ("금융지원 후보 상태",),
    "company.ksure_exporter_grade": ("금융지원 후보 상태",),
    "company.is_domestic": ("금융지원 후보 상태",),
    "payment.is_netting": ("외국환 신고 판정", "다음 행동"),
    "payment.is_third_party": ("외국환 신고 판정", "다음 행동"),
    "payment.uses_mutual_account": ("외국환 신고 판정", "다음 행동"),
    "payment.uses_foreign_exchange_bank": ("외국환 신고 판정", "다음 행동"),
    "baseline_profit": ("헤지 손실한도", "헤지 비율"),
    "profit_floor": ("헤지 손실한도", "헤지 비율"),
}

FIELD_PRIORITY = {
    "opening_balance_usd": 0,
    "financing.has_bank_consultation": 10,
    "financing.purpose": 11,
    "trade.payment_term_days": 20,
    "payment.is_netting": 30,
    "payment.is_third_party": 31,
    "payment.uses_mutual_account": 32,
    "payment.uses_foreign_exchange_bank": 33,
    "company.size": 40,
    "company.credit_issue_free": 41,
    "company.ksure_exporter_grade": 42,
    "company.is_domestic": 43,
    "baseline_profit": 50,
    "profit_floor": 51,
}

ACTION_LABELS = {
    "consult_and_apply_for_ksure_product": "K-SURE 상담 후 상품 신청",
    "consult_and_apply_for_preshipment_guarantee": "선적전 수출신용보증 상담·신청",
    "file_report": "신고서 제출",
    "consult_designated_bank": "지정 외국환은행 상담",
}

USER_SCOPES = frozenset({"profile", "compliance_declaration", "case", "hedge"})


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _funding_gaps(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list((result.get("cashflow_analysis") or {}).get("funding_gap") or [])


def _decision_impact_counts(
    result: Mapping[str, Any],
) -> dict[tuple[str | None, str], int]:
    """Count the decisions for which one missing fact is a blocker."""
    counts: dict[tuple[str | None, str], int] = {}
    for collection in ("support_candidates", "excluded_candidates", "risk_findings"):
        for decision in result.get(collection) or []:
            subject_id = decision.get("subject_id")
            for field in set(decision.get("missing_fields") or []):
                key = (subject_id, str(field))
                counts[key] = counts.get(key, 0) + 1
    return counts


def build_next_decisive_questions(
    result: Mapping[str, Any],
    *,
    opening_balances: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Rank user-provided facts by the decision they can change."""
    questions: list[dict[str, Any]] = []
    balances = {key.upper(): value for key, value in (opening_balances or {}).items()}
    impact_counts = _decision_impact_counts(result)

    # An unrecorded balance is not a required rule input, but it is often the
    # single fact with the largest direct effect on a company's funding gap.
    for gap in _funding_gaps(result):
        currency = str(gap.get("currency") or "").upper()
        peak = _decimal(gap.get("peak_amount"))
        if currency != "USD" or peak is None or peak <= 0 or currency in balances:
            continue
        questions.append({
            "question_id": "liquidity.opening_balance.USD",
            "field": "opening_balance_usd",
            "fields": ["opening_balance_usd"],
            "scope": "liquidity",
            "subject_id": currency,
            "actor": "user",
            "question": FIELD_QUESTIONS["opening_balance_usd"],
            "changes": ["최대 자금 공백"],
            "reason": (
                "보유 외화는 부족액에 우선 충당되므로 입력 금액만큼 "
                "최대 자금 공백이 줄어듭니다."
            ),
            "impact_preview": {
                "metric": "funding_gap",
                "currency": currency,
                "current": str(peak),
                "formula": "max(0, current_funding_gap - opening_balance)",
            },
            "priority": FIELD_PRIORITY["opening_balance_usd"],
            "affected_decision_count": 1,
        })

    seen = {item["question_id"] for item in questions}
    for item in result.get("missing_input_queue") or []:
        field = item.get("field")
        if not field or item.get("scope") not in USER_SCOPES:
            continue
        question_id = f"decision-input:{item.get('subject_id') or 'program'}:{field}"
        if question_id in seen:
            continue
        seen.add(question_id)
        impacts = list(FIELD_IMPACTS.get(field, ("판정 상태",)))
        affected_decision_count = max(
            1,
            impact_counts.get((item.get("subject_id"), field), 0),
        )
        questions.append({
            "question_id": question_id,
            "field": field,
            "fields": [field],
            "scope": item.get("scope"),
            "subject_id": item.get("subject_id"),
            "actor": "user",
            "question": FIELD_QUESTIONS.get(field, f"{field} 값을 확인해 주세요."),
            "changes": impacts,
            "reason": item.get("reason") or "현재 판정에 필요한 정보입니다.",
            "impact_preview": None,
            "priority": FIELD_PRIORITY.get(field, 90),
            "affected_decision_count": affected_decision_count,
        })

    return sorted(
        questions,
        key=lambda item: (
            0 if item["field"] == "opening_balance_usd" else 1,
            -item["affected_decision_count"],
            item["priority"],
            item.get("subject_id") or "",
            item["field"],
        ),
    )


def _by_currency(entries: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(item.get("currency")): item for item in entries if item.get("currency")}


def _metric_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[dict[str, Any]]:
    labels = {
        "funding_gap": ("peak_amount", "최대 자금 공백"),
        "net_exposure": ("amount", "순노출"),
        "natural_hedge_amount": ("amount", "자연헤지 금액"),
        "maturity_matched_amount": ("amount", "결제일 일치 금액"),
    }
    before_cashflow = before.get("cashflow_analysis") or {}
    after_cashflow = after.get("cashflow_analysis") or {}
    changes: list[dict[str, Any]] = []
    for metric, (value_key, label) in labels.items():
        old = _by_currency(before_cashflow.get(metric) or [])
        new = _by_currency(after_cashflow.get(metric) or [])
        for currency in sorted(set(old) | set(new)):
            before_value = old.get(currency, {}).get(value_key, "0")
            after_value = new.get(currency, {}).get(value_key, "0")
            if _decimal(before_value) == _decimal(after_value):
                continue
            changes.append({
                "kind": "cashflow_metric",
                "metric": metric,
                "label": label,
                "subject_id": currency,
                "before": str(before_value),
                "after": str(after_value),
                "unit": currency,
            })
    return changes


def _candidate_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[dict[str, Any]]:
    def index(result: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
        indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
        for collection in ("support_candidates", "excluded_candidates"):
            for item in result.get(collection) or []:
                key = (str(item.get("subject_id")), str(item.get("rule_id")))
                indexed[key] = item
        return indexed

    old = index(before)
    new = index(after)
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        before_item = old.get(key, {})
        after_item = new.get(key, {})
        before_status = before_item.get("status", "not_present")
        after_status = after_item.get("status", "not_present")
        if before_status == after_status:
            continue
        changes.append({
            "kind": "support_candidate_status",
            "metric": "support_candidate_status",
            "label": after_item.get("title") or before_item.get("title") or key[1],
            "subject_id": key[0],
            "rule_id": key[1],
            "before": before_status,
            "after": after_status,
            "source_ids": after_item.get("source_ids") or before_item.get("source_ids") or [],
        })
    return changes


def _action_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> list[dict[str, Any]]:
    def index(
        result: Mapping[str, Any],
    ) -> dict[tuple[str, str, str, str, str, tuple[str, ...]], Mapping[str, Any]]:
        return {
            (
                str(item.get("subject_id")),
                str(item.get("action")),
                str(item.get("authority")),
                str(item.get("timing")),
                str(item.get("deadline")),
                tuple(sorted(str(value) for value in item.get("product_ids") or [])),
            ): item
            for item in result.get("next_actions") or []
        }

    old = index(before)
    new = index(after)
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        before_item = old.get(key)
        after_item = new.get(key)
        action = (after_item or before_item or {}).get("action")
        label = ACTION_LABELS.get(str(action), str(action))
        if before_item is None or after_item is None:
            changes.append({
                "kind": "decision_action",
                "metric": "next_action",
                "label": label,
                "subject_id": key[0],
                "action": action,
                "authority": (after_item or before_item or {}).get("authority"),
                "before": "not_required" if before_item is None else "required",
                "after": "not_required" if after_item is None else "required",
                "source_ids": (
                    (after_item or before_item or {}).get("source_ids") or []
                ),
            })
            continue

        before_documents = sorted(before_item.get("required_documents") or [])
        after_documents = sorted(after_item.get("required_documents") or [])
        if before_documents != after_documents:
            changes.append({
                "kind": "required_documents",
                "metric": "required_documents",
                "label": f"{label} 필요서류",
                "subject_id": key[0],
                "action": action,
                "before": before_documents,
                "after": after_documents,
                "source_ids": after_item.get("source_ids") or [],
            })
    return changes


def compare_decisions(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    previous_analysis_run_id: str,
) -> dict[str, Any]:
    """Return only material, reproducible changes between two decisions."""
    changes = [
        *_metric_changes(before, after),
        *_candidate_changes(before, after),
        *_action_changes(before, after),
    ]
    previous_questions = {
        str(item.get("question_id")): item
        for item in before.get("next_decisive_questions") or []
    }
    current_question_ids = {
        str(item.get("question_id"))
        for item in after.get("next_decisive_questions") or []
    }
    resolved = [
        {
            "question_id": question_id,
            "field": item.get("field"),
            "question": item.get("question"),
        }
        for question_id, item in sorted(previous_questions.items())
        if question_id not in current_question_ids
    ]
    return {
        "schema_version": "1.0",
        "previous_analysis_run_id": previous_analysis_run_id,
        "previous_packet_id": before.get("packet_id"),
        "current_packet_id": after.get("packet_id"),
        "changed": bool(changes or resolved),
        "changes": changes,
        "resolved_questions": resolved,
        "change_count": len(changes),
    }
