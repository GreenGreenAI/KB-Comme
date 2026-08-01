"""Executable benchmark for profile classification and policy routing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping

from tradeflow.runtime.profile_policy import evaluate_profile_policy


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = ROOT / "benchmarks" / "user_profile_policy_cases.json"
BASELINE_PATH = ROOT / "benchmarks" / "user_profile_policy_baseline.json"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: Any
    actual: Any


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario_id: str
    title: str
    track: str
    critical: bool
    latency_ms: float
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(item.passed for item in self.checks)


@dataclass(frozen=True)
class BenchmarkReport:
    benchmark_id: str
    outcomes: tuple[ScenarioOutcome, ...]

    @property
    def scenarios_passed(self) -> int:
        return sum(item.passed for item in self.outcomes)

    @property
    def checks_passed(self) -> int:
        return sum(
            check.passed for outcome in self.outcomes for check in outcome.checks
        )

    @property
    def checks_total(self) -> int:
        return sum(len(outcome.checks) for outcome in self.outcomes)


def load_benchmark() -> dict[str, Any]:
    return json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _check(name: str, actual: Any, expected: Any) -> Check:
    return Check(name=name, passed=actual == expected, expected=expected, actual=actual)


def _contains_all(actual: Iterable[Any], expected: Iterable[Any]) -> bool:
    return set(expected).issubset(set(actual))


def _classification_evidence_ids(result: Mapping[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            evidence_id
            for item in result.get("classifications") or []
            for evidence_id in item.get("evidence_ids") or []
        )
    )


def _contains_endpoint_shape(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(str(key).lower() in {"endpoint", "url"} for key in value):
            return True
        return any(_contains_endpoint_shape(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_endpoint_shape(item) for item in value)
    if isinstance(value, str):
        return value.startswith(("GET /", "POST /", "PUT /", "DELETE /"))
    return False


def _value_at(result: Mapping[str, Any], path: str) -> Any:
    value: Any = result
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _evaluate_expectation(
    result: Mapping[str, Any], expected: Mapping[str, Any]
) -> tuple[Check, ...]:
    checks: list[Check] = []
    exact_keys = (
        "primary_type",
        "fact_status",
        "used_provenance",
        "review_required",
        "fallback",
        "decision_status",
        "handoff_mode",
        "transmission_performed",
    )
    for key in exact_keys:
        if key in expected:
            checks.append(_check(key, result.get(key), expected[key]))

    include_mappings = {
        "secondary_types_include": "secondary_types",
        "missing_fields_include": "missing_fields",
        "classification_evidence_ids_include": None,
        "route_capabilities_include": "route_capabilities",
        "authorized_capabilities_include": "authorized_capabilities",
        "missing_consents_include": "missing_consents",
    }
    for expectation_key, result_key in include_mappings.items():
        if expectation_key not in expected:
            continue
        actual = (
            _classification_evidence_ids(result)
            if result_key is None
            else result.get(result_key) or []
        )
        checks.append(
            _check(
                expectation_key,
                _contains_all(actual, expected[expectation_key]),
                True,
            )
        )

    if "unsupported_types_absent" in expected:
        actual_types = {
            result.get("primary_type"),
            *(result.get("secondary_types") or []),
        }
        forbidden = set(expected["unsupported_types_absent"])
        checks.append(
            _check("unsupported_types_absent", sorted(actual_types & forbidden), [])
        )

    if "axes_include" in expected:
        axes = result.get("axes") or {}
        actual = all(
            _contains_all(axes.get(axis) or [], values)
            for axis, values in expected["axes_include"].items()
        )
        checks.append(_check("axes_include", actual, True))

    if "forbidden_claims" in expected:
        claims = set(result.get("claims") or [])
        forbidden = set(expected["forbidden_claims"])
        checks.append(_check("forbidden_claims", sorted(claims & forbidden), []))

    if "allowed_outputs" in expected:
        checks.append(
            _check(
                "allowed_outputs",
                sorted(result.get("allowed_outputs") or []),
                sorted(expected["allowed_outputs"]),
            )
        )

    if "required_consent" in expected:
        checks.append(
            _check(
                "required_consent",
                expected["required_consent"]
                in (result.get("required_consents") or []),
                True,
            )
        )

    if "fabricated_endpoint_absent" in expected:
        checks.append(
            _check(
                "fabricated_endpoint_absent",
                not _contains_endpoint_shape(result),
                True,
            )
        )

    if "executed_capabilities_absent" in expected:
        executed = set(result.get("executed_capabilities") or [])
        forbidden = set(expected["executed_capabilities_absent"])
        checks.append(
            _check(
                "executed_capabilities_absent",
                sorted(executed & forbidden),
                [],
            )
        )

    if expected.get("string_comparison_forbidden"):
        checks.append(
            _check(
                "string_comparison_forbidden",
                True,
                True,
            )
        )
    return tuple(checks)


def _evaluate_pair(
    scenario: Mapping[str, Any]
) -> tuple[Check, ...]:
    pair = scenario["pair"]
    base = evaluate_profile_policy(pair["base"]).as_dict()
    variant = evaluate_profile_policy(pair["variant"]).as_dict()
    expected = scenario["expect"]
    checks: list[Check] = []
    for path in expected.get("invariant_fields") or []:
        checks.append(
            _check(
                f"invariant:{path}",
                _value_at(variant, path),
                _value_at(base, path),
            )
        )
    if expected.get("string_comparison_forbidden"):
        base_stage = _value_at(base, "axes.company_stage")
        variant_stage = _value_at(variant, "axes.company_stage")
        checks.append(
            _check(
                "numeric_boundary_changes_stage",
                base_stage != variant_stage,
                True,
            )
        )
    return tuple(checks)


def run_scenario(scenario: Mapping[str, Any]) -> ScenarioOutcome:
    started = perf_counter()
    if "pair" in scenario:
        checks = _evaluate_pair(scenario)
    else:
        result = evaluate_profile_policy(scenario["input"]).as_dict()
        checks = _evaluate_expectation(result, scenario["expect"])
    elapsed = (perf_counter() - started) * 1000
    return ScenarioOutcome(
        scenario_id=scenario["id"],
        title=scenario["title"],
        track=scenario["track"],
        critical=bool(scenario.get("critical")),
        latency_ms=elapsed,
        checks=checks,
    )


def run_benchmark() -> BenchmarkReport:
    benchmark = load_benchmark()
    return BenchmarkReport(
        benchmark_id="TRADEFLOW_USER_PROFILE_POLICY_V1",
        outcomes=tuple(run_scenario(item) for item in benchmark["scenarios"]),
    )


def report_as_dict(report: BenchmarkReport) -> dict[str, Any]:
    return {
        "benchmark_id": report.benchmark_id,
        "scenario_success": {
            "passed": report.scenarios_passed,
            "total": len(report.outcomes),
            "rate": report.scenarios_passed / len(report.outcomes),
        },
        "check_success": {
            "passed": report.checks_passed,
            "total": report.checks_total,
            "rate": report.checks_passed / report.checks_total,
        },
        "scenarios": [
            {
                "id": item.scenario_id,
                "title": item.title,
                "track": item.track,
                "critical": item.critical,
                "passed": item.passed,
                "latency_ms": round(item.latency_ms, 3),
                "checks": [
                    {
                        "name": check.name,
                        "passed": check.passed,
                        "expected": check.expected,
                        "actual": check.actual,
                    }
                    for check in item.checks
                ],
            }
            for item in report.outcomes
        ],
    }
