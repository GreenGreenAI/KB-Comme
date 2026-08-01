"""Run customer jobs through the real web application boundary.

The benchmark scores structured outcomes, never generated prose. It complements
the capability-oriented acceptance harness by asking whether one customer job
was completed end to end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from tradeflow.runtime.accounts import AccountStore
from tradeflow.web import app as web_app
from tests.acceptance.harness import run_all as run_capability_scenarios


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = ROOT / "benchmarks" / "user_tasks.json"
BASELINE_PATH = ROOT / "benchmarks" / "user_tasks_baseline.json"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: Any
    actual: Any


@dataclass(frozen=True)
class TaskOutcome:
    scenario_id: str
    title: str
    metric: str
    critical: bool
    latency_ms: float
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


@dataclass(frozen=True)
class BenchmarkReport:
    benchmark_id: str
    outcomes: tuple[TaskOutcome, ...]
    capabilities_met: int
    capabilities_total: int

    @property
    def tasks_passed(self) -> int:
        return sum(outcome.passed for outcome in self.outcomes)

    @property
    def task_success_rate(self) -> float:
        return self.tasks_passed / len(self.outcomes)

    @property
    def checks_passed(self) -> int:
        return sum(
            check.passed
            for outcome in self.outcomes
            for check in outcome.checks
        )

    @property
    def checks_total(self) -> int:
        return sum(len(outcome.checks) for outcome in self.outcomes)

    @property
    def check_success_rate(self) -> float:
        return self.checks_passed / self.checks_total

    @property
    def median_latency_ms(self) -> float:
        return median(outcome.latency_ms for outcome in self.outcomes)

    @property
    def p95_latency_ms(self) -> float:
        ordered = sorted(outcome.latency_ms for outcome in self.outcomes)
        index = max(0, ceil(len(ordered) * 0.95) - 1)
        return ordered[index]


def load_benchmark() -> dict[str, Any]:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _check(name: str, actual: Any, expected: Any) -> Check:
    return Check(name, actual == expected, expected, actual)


def _first_amount(items: list[dict[str, Any]] | None, key: str) -> Any:
    if not items:
        return None
    return items[0].get(key)


def _evaluate_analyze(
    body: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[Check, ...]:
    checks: list[Check] = []
    if "status" in expected:
        checks.append(_check("status", body.get("status"), expected["status"]))
    if expected.get("result_absent"):
        checks.append(_check("result_absent", "result" not in body, True))

    candidates = body.get("candidates") or []
    if "candidate_summaries" in expected:
        actual = [
            {
                key: item.get(key)
                for key in ("direction", "amount", "expected_payment_date")
            }
            for item in candidates
        ]
        checks.append(
            _check("candidate_summaries", actual, expected["candidate_summaries"])
        )

    result = body.get("result") or {}
    if expected.get("summary_nonempty"):
        checks.append(
            _check(
                "summary_nonempty",
                bool(str(result.get("summary") or "").strip()),
                True,
            )
        )
    if "trade_count" in expected:
        checks.append(
            _check(
                "trade_count",
                len(result.get("trade_timeline") or []),
                expected["trade_count"],
            )
        )
    if "review_required" in expected:
        checks.append(
            _check(
                "review_required",
                result.get("review_required"),
                expected["review_required"],
            )
        )
    if "cashflow" in expected:
        cashflow = result.get("cashflow_analysis") or {}
        actual_cashflow = {
            "funding_gap": _first_amount(
                cashflow.get("funding_gap"), "peak_amount"
            ),
            "net_exposure": _first_amount(
                cashflow.get("net_exposure"), "amount"
            ),
            "natural_hedge": _first_amount(
                cashflow.get("natural_hedge_amount"), "amount"
            ),
            "maturity_matched": _first_amount(
                cashflow.get("maturity_matched_amount"), "amount"
            ),
        }
        checks.append(
            _check("cashflow", actual_cashflow, expected["cashflow"])
        )
    if "market_scenario" in expected:
        market = result.get("market_scenario") or {}
        wanted_market = expected["market_scenario"]
        actual_market = {
            key: market.get(key)
            for key in wanted_market
        }
        checks.append(
            _check("market_scenario", actual_market, wanted_market)
        )
    if "hedge_analysis" in expected:
        hedge = result.get("hedge_analysis") or {}
        wanted_hedge = expected["hedge_analysis"]
        actual_hedge = {
            key: hedge.get(key)
            for key in wanted_hedge
            if key != "payoff_points"
        }
        if "payoff_points" in wanted_hedge:
            points = {
                f"{scenario.get('label')}:{point.get('label')}": point.get(
                    "profit"
                )
                for scenario in hedge.get("payoff_comparison") or []
                for point in scenario.get("points") or []
            }
            actual_hedge["payoff_points"] = {
                key: points.get(key)
                for key in wanted_hedge["payoff_points"]
            }
        checks.append(
            _check("hedge_analysis", actual_hedge, wanted_hedge)
        )
    if "workers_completed_include" in expected:
        completed = set((result.get("workers") or {}).get("completed") or [])
        wanted_workers = set(expected["workers_completed_include"])
        checks.append(
            _check(
                "workers_completed_include",
                sorted(completed & wanted_workers),
                sorted(wanted_workers),
            )
        )
    if "missing_fields_absent" in expected:
        missing = {
            item.get("field")
            for item in result.get("missing_input_queue") or []
        }
        forbidden = set(expected["missing_fields_absent"])
        checks.append(
            _check(
                "missing_fields_absent",
                sorted(missing & forbidden),
                [],
            )
        )
    if "decision" in expected:
        wanted = expected["decision"]
        decision = next(
            (
                item
                for item in result.get("support_candidates") or []
                if item.get("rule_id") == wanted["rule_id"]
            ),
            None,
        )
        actual = None if decision is None else {
            "rule_id": decision.get("rule_id"),
            "matched": decision.get("matched"),
            "status": decision.get("status"),
        }
        checks.append(_check("decision", actual, wanted))
    if "action_authority" in expected:
        authorities = {
            item.get("authority")
            for item in result.get("next_actions") or []
        }
        checks.append(
            _check(
                "action_authority",
                expected["action_authority"] in authorities,
                True,
            )
        )
    if expected.get("evidence_sources_nonempty"):
        candidates_with_outcomes = [
            item
            for item in result.get("support_candidates") or []
            if item.get("outcome")
        ]
        actual = bool(candidates_with_outcomes) and all(
            item.get("source_ids") for item in candidates_with_outcomes
        )
        checks.append(_check("evidence_sources_nonempty", actual, True))
    if "issue_field" in expected:
        issue_fields = {item.get("field") for item in body.get("issues") or []}
        checks.append(
            _check(
                "issue_field",
                expected["issue_field"] in issue_fields,
                True,
            )
        )
    return tuple(checks)


def _run_handoff(scenario: dict[str, Any]) -> dict[str, Any]:
    account_spec = scenario["account"]
    with TemporaryDirectory() as directory:
        store = AccountStore(Path(directory) / "accounts.db")
        account = store.create(
            account_spec["email"],
            account_spec["password"],
            company_name=account_spec["company_name"],
            account_id=account_spec["account_id"],
        )
        account = store.update_facts(account, account_spec.get("facts") or {})
        with patch("tradeflow.web.app.accounts", store):
            with TestClient(web_app.app) as client:
                login = client.post("/api/auth/login", json={
                    "email": account_spec["email"],
                    "password": account_spec["password"],
                })
                login.raise_for_status()
                analyzed = client.post(
                    "/api/analyze",
                    json=scenario["request"],
                )
                analyzed.raise_for_status()
                analysis = analyzed.json()
                handed_off = client.post(
                    f"/api/analyses/{analysis['analysis_run_id']}"
                    "/consultation-handoff",
                    json={"consent": True},
                )
                handed_off.raise_for_status()
                handoff = handed_off.json()["handoff"]
            audit = list(store.list_audit(account))
    return {"analysis": analysis, "handoff": handoff, "audit": audit}


def _evaluate_handoff(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[Check, ...]:
    handoff = payload["handoff"]
    expected_handoff = expected["handoff"]
    channel = handoff.get("channel") or {}
    privacy = handoff.get("privacy") or {}
    actual = {
        "state": handoff.get("state"),
        "mode": channel.get("mode"),
        "target_bank": channel.get("target_bank"),
        "transmission_performed": privacy.get("transmission_performed"),
        "raw_document_content_included": privacy.get(
            "raw_document_content_included"
        ),
    }
    audit_actions = {item.get("action") for item in payload["audit"]}
    return (
        _check(
            "analysis_status",
            payload["analysis"].get("status"),
            expected["analysis_status"],
        ),
        _check("handoff", actual, expected_handoff),
        _check(
            "audit_action",
            expected["audit_action"] in audit_actions,
            True,
        ),
    )


def _run_handoff_safety(scenario: dict[str, Any]) -> dict[str, Any]:
    owner_spec = scenario["account"]
    intruder_spec = scenario["intruder"]
    with TemporaryDirectory() as directory:
        store = AccountStore(Path(directory) / "accounts.db")
        owner = store.create(
            owner_spec["email"],
            owner_spec["password"],
            company_name=owner_spec["company_name"],
            account_id=owner_spec["account_id"],
        )
        intruder = store.create(
            intruder_spec["email"],
            intruder_spec["password"],
            company_name=intruder_spec["company_name"],
            account_id=intruder_spec["account_id"],
        )
        with patch("tradeflow.web.app.accounts", store):
            with (
                TestClient(web_app.app) as owner_client,
                TestClient(web_app.app) as intruder_client,
            ):
                owner_login = owner_client.post("/api/auth/login", json={
                    "email": owner_spec["email"],
                    "password": owner_spec["password"],
                })
                owner_login.raise_for_status()
                intruder_login = intruder_client.post("/api/auth/login", json={
                    "email": intruder_spec["email"],
                    "password": intruder_spec["password"],
                })
                intruder_login.raise_for_status()
                analyzed = owner_client.post(
                    "/api/analyze",
                    json=scenario["request"],
                )
                analyzed.raise_for_status()
                run_id = analyzed.json()["analysis_run_id"]
                path = f"/api/analyses/{run_id}/consultation-handoff"
                first_response = owner_client.post(
                    path,
                    json={"consent": True},
                )
                first_response.raise_for_status()
                first = first_response.json()["handoff"]
                second_response = owner_client.post(
                    path,
                    json={"consent": True},
                )
                second_response.raise_for_status()
                second = second_response.json()["handoff"]
                intruder_status = intruder_client.post(
                    path,
                    json={"consent": True},
                ).status_code
    return {
        "first": first,
        "second": second,
        "intruder_status": intruder_status,
    }


def _evaluate_handoff_safety(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[Check, ...]:
    first = payload["first"]
    second = payload["second"]
    return (
        _check(
            "stable_handoff_id",
            second.get("handoff_id"),
            first.get("handoff_id"),
        ),
        _check(
            "transmission_performed",
            (second.get("privacy") or {}).get("transmission_performed"),
            expected["transmission_performed"],
        ),
        _check(
            "cross_tenant_status",
            payload["intruder_status"],
            expected["cross_tenant_status"],
        ),
    )


def _run_decision_delta(scenario: dict[str, Any]) -> dict[str, Any]:
    account_spec = scenario["account"]
    with TemporaryDirectory() as directory:
        store = AccountStore(Path(directory) / "accounts.db")
        account = store.create(
            account_spec["email"],
            account_spec["password"],
            company_name=account_spec["company_name"],
            account_id=account_spec["account_id"],
        )
        store.update_facts(account, account_spec.get("facts") or {})
        with patch("tradeflow.web.app.accounts", store):
            with TestClient(web_app.app) as client:
                login = client.post("/api/auth/login", json={
                    "email": account_spec["email"],
                    "password": account_spec["password"],
                })
                login.raise_for_status()
                first_response = client.post(
                    "/api/analyze",
                    json=scenario["before_request"],
                )
                first_response.raise_for_status()
                first = first_response.json()
                after_request = {
                    **scenario["after_request"],
                    "previous_analysis_run_id": first["analysis_run_id"],
                }
                second_response = client.post("/api/analyze", json=after_request)
                second_response.raise_for_status()
                second = second_response.json()
                passport_response = client.post(
                    f"/api/analyses/{second['analysis_run_id']}"
                    "/consultation-handoff",
                    json={"consent": True},
                )
                passport_response.raise_for_status()
                passport = passport_response.json()["handoff"]
    return {"first": first, "second": second, "passport": passport}


def _evaluate_decision_delta(
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[Check, ...]:
    first_result = payload["first"]["result"]
    second_result = payload["second"]["result"]
    delta = second_result.get("decision_delta") or {}
    changes = delta.get("changes") or []
    gap = next(
        (item for item in changes if item.get("metric") == "funding_gap"),
        {},
    )
    candidate = next(
        (
            item
            for item in changes
            if item.get("rule_id") == expected["candidate"]["rule_id"]
        ),
        {},
    )
    passport_delta = (
        payload["passport"].get("decision_experience") or {}
    ).get("decision_delta")
    return (
        _check(
            "first_decisive_question",
            (first_result.get("next_decisive_questions") or [{}])[0].get("field"),
            expected["first_decisive_question"],
        ),
        _check(
            "funding_gap_delta",
            {"before": gap.get("before"), "after": gap.get("after")},
            expected["funding_gap"],
        ),
        _check(
            "candidate_status_delta",
            {"before": candidate.get("before"), "after": candidate.get("after")},
            {
                "before": expected["candidate"]["before"],
                "after": expected["candidate"]["after"],
            },
        ),
        _check("passport_type", payload["passport"].get("packet_type"), "decision_passport"),
        _check("passport_preserves_delta", passport_delta, delta),
    )


def run_scenario(scenario: dict[str, Any]) -> TaskOutcome:
    started = perf_counter()
    if scenario["kind"] == "analyze":
        with TestClient(web_app.app) as client:
            response = client.post("/api/analyze", json=scenario["request"])
            response.raise_for_status()
            body = response.json()
        checks = _evaluate_analyze(body, scenario["expect"])
    elif scenario["kind"] == "consultation_handoff":
        payload = _run_handoff(scenario)
        checks = _evaluate_handoff(payload, scenario["expect"])
    elif scenario["kind"] == "consultation_handoff_safety":
        payload = _run_handoff_safety(scenario)
        checks = _evaluate_handoff_safety(payload, scenario["expect"])
    elif scenario["kind"] == "decision_delta":
        payload = _run_decision_delta(scenario)
        checks = _evaluate_decision_delta(payload, scenario["expect"])
    else:
        raise ValueError(f"unknown benchmark scenario kind: {scenario['kind']}")
    elapsed = (perf_counter() - started) * 1000
    return TaskOutcome(
        scenario_id=scenario["id"],
        title=scenario["title"],
        metric=scenario["metric"],
        critical=bool(scenario.get("critical")),
        latency_ms=elapsed,
        checks=checks,
    )


def run_benchmark() -> BenchmarkReport:
    benchmark = load_benchmark()
    outcomes = tuple(run_scenario(item) for item in benchmark["scenarios"])
    capability_outcomes = run_capability_scenarios()
    capabilities_met = sum(len(item.met) for item in capability_outcomes)
    capabilities_total = sum(
        len(item.met) + len(item.missing)
        for item in capability_outcomes
    )
    return BenchmarkReport(
        benchmark_id=benchmark["benchmark_id"],
        outcomes=outcomes,
        capabilities_met=capabilities_met,
        capabilities_total=capabilities_total,
    )


def report_as_dict(report: BenchmarkReport) -> dict[str, Any]:
    return {
        "benchmark_id": report.benchmark_id,
        "transport": "http_asgi_testclient",
        "task_success": {
            "passed": report.tasks_passed,
            "total": len(report.outcomes),
            "rate": report.task_success_rate,
        },
        "check_success": {
            "passed": report.checks_passed,
            "total": report.checks_total,
            "rate": report.check_success_rate,
        },
        "capability_acceptance": {
            "met": report.capabilities_met,
            "total": report.capabilities_total,
        },
        "latency_ms": {
            "median": round(report.median_latency_ms, 2),
            "p95": round(report.p95_latency_ms, 2),
        },
        "scenarios": [
            {
                "id": outcome.scenario_id,
                "title": outcome.title,
                "metric": outcome.metric,
                "critical": outcome.critical,
                "passed": outcome.passed,
                "latency_ms": round(outcome.latency_ms, 2),
                "checks": [
                    {
                        "name": check.name,
                        "passed": check.passed,
                        "expected": check.expected,
                        "actual": check.actual,
                    }
                    for check in outcome.checks
                ],
            }
            for outcome in report.outcomes
        ],
    }
