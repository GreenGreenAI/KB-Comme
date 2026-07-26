from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from tradeflow.knowledge.models import Condition


@dataclass(frozen=True)
class ConditionResult:
    condition: Condition
    status: str  # passed | failed | uncertain
    reason: str


def evaluate_condition(condition: Condition, facts: Mapping[str, Any]) -> ConditionResult:
    if condition.field not in facts or facts[condition.field] is None:
        return ConditionResult(
            condition,
            "uncertain",
            f"missing fact: {condition.field}",
        )

    actual = facts[condition.field]
    try:
        passed = _compare(actual, condition.operator, condition.value)
    except (TypeError, ValueError) as exc:
        return ConditionResult(condition, "uncertain", f"comparison error: {exc}")
    status = "passed" if passed else "failed"
    return ConditionResult(
        condition,
        status,
        f"{condition.field}={actual!s} {condition.operator} {condition.value!s}",
    )


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator in {"gt", "gte", "lt", "lte"}:
        left, right = Decimal(str(actual)), Decimal(str(expected))
        return {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[operator]
    if operator == "eq":
        return actual == expected
    if operator == "not_eq":
        return actual != expected
    if operator == "in":
        return actual in expected
    if operator == "not_in":
        return actual not in expected
    if operator == "exists":
        return (actual is not None) is bool(expected)
    raise ValueError(f"unsupported operator: {operator}")

