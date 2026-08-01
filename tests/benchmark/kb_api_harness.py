"""Observe the eight KB user-type use cases through POST /api/analyze."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient

from tradeflow.web.app import app


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "benchmarks" / "kb_user_type_api_cases.json"


def _result(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("result") or {}


def _cash(body: dict[str, Any], key: str) -> bool:
    return bool((_result(body).get("cashflow_analysis") or {}).get(key))


def _system_ids(body: dict[str, Any]) -> set[str]:
    return {
        item.get("capability_id")
        for item in _result(body).get("system_fetches") or []
    }


CAPABILITIES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "exposure": lambda body: _cash(body, "net_exposure"),
    "funding_gap": lambda body: _cash(body, "funding_gap"),
    "natural_hedge": lambda body: _cash(body, "natural_hedge_amount"),
    "market_scenario": lambda body: bool(_result(body).get("market_scenario")),
    "hedge_ratio": lambda body: (
        (_result(body).get("hedge_analysis") or {}).get("optimal_ratio")
        is not None
    ),
    "payoff_comparison": lambda body: bool(
        (_result(body).get("hedge_analysis") or {}).get("payoff_comparison")
    ),
    "support_ksure": lambda body: bool(
        _result(body).get("support_candidates")
    ),
    "profile_policy": lambda body: bool(_result(body).get("profile_policy")),
    "expert_task": lambda body: bool(_result(body).get("expert_tasks")),
    "system_fetch_partition": lambda body: bool(
        _result(body).get("system_fetches")
    ),
    "country_risk_lookup_requested": lambda body: (
        "ksure.country_policy.lookup.v1" in _system_ids(body)
    ),
    "buyer_credit_lookup_requested": lambda body: (
        "ksure.importer_grade.lookup.v1" in _system_ids(body)
    ),
}


@dataclass(frozen=True)
class ApiObservation:
    scenario_id: str
    user_type: str
    query: str
    http_status: int
    response: dict[str, Any]
    required_met: tuple[str, ...]
    required_missing: tuple[str, ...]
    desired_met: tuple[str, ...]
    desired_missing: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.http_status == 200 and not self.required_missing


def load_cases() -> dict[str, Any]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def _observed_response(body: dict[str, Any]) -> dict[str, Any]:
    result = _result(body)
    hedge = result.get("hedge_analysis") or {}
    market = result.get("market_scenario") or {}
    return {
        "status": body.get("status"),
        "summary": result.get("summary"),
        "cashflow_analysis": result.get("cashflow_analysis"),
        "market_scenario": {
            key: market.get(key)
            for key in (
                "spot_rate",
                "band_lower",
                "band_upper",
                "adverse_cashflow_amount",
            )
            if market
        } or None,
        "hedge_analysis": {
            "optimal_ratio": hedge.get("optimal_ratio"),
            "adverse_rate": hedge.get("adverse_rate"),
            "payoff_comparison": hedge.get("payoff_comparison"),
        } if hedge else None,
        "support_candidates": [
            {"title": item.get("title"), "status": item.get("status")}
            for item in result.get("support_candidates") or []
        ],
        "system_fetches": result.get("system_fetches") or [],
        "expert_tasks": result.get("expert_tasks") or [],
    }


def run_api_audit() -> tuple[ApiObservation, ...]:
    observations: list[ApiObservation] = []
    with TestClient(app) as client:
        for scenario in load_cases()["scenarios"]:
            response = client.post("/api/analyze", json=scenario["request"])
            body = response.json()
            required = tuple(scenario.get("required_capabilities") or [])
            desired = tuple(scenario.get("desired_capabilities") or [])
            required_met = tuple(
                item for item in required
                if CAPABILITIES.get(item, lambda _: False)(body)
            )
            desired_met = tuple(
                item for item in desired
                if CAPABILITIES.get(item, lambda _: False)(body)
            )
            observations.append(ApiObservation(
                scenario_id=scenario["id"],
                user_type=scenario["user_type"],
                query=scenario["query"],
                http_status=response.status_code,
                response=_observed_response(body),
                required_met=required_met,
                required_missing=tuple(
                    item for item in required if item not in required_met
                ),
                desired_met=desired_met,
                desired_missing=tuple(
                    item for item in desired if item not in desired_met
                ),
            ))
    return tuple(observations)


def report_as_dict(observations: tuple[ApiObservation, ...]) -> dict[str, Any]:
    return {
        "benchmark_id": "TRADEFLOW_KB_USER_TYPE_API_V1",
        "transport": "POST /api/analyze via ASGI HTTP TestClient",
        "required_success": {
            "passed": sum(item.passed for item in observations),
            "total": len(observations),
        },
        "observations": [
            {
                "id": item.scenario_id,
                "user_type": item.user_type,
                "query": item.query,
                "http_status": item.http_status,
                "passed": item.passed,
                "required_met": list(item.required_met),
                "required_missing": list(item.required_missing),
                "desired_met": list(item.desired_met),
                "desired_missing": list(item.desired_missing),
                "response": item.response,
            }
            for item in observations
        ],
    }
