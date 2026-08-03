"""Print the customer-task benchmark as text or JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.benchmark.harness import report_as_dict, run_benchmark  # noqa: E402


def _text_report(payload: dict) -> None:
    tasks = payload["task_success"]
    checks = payload["check_success"]
    capability = payload["capability_acceptance"]
    latency = payload["latency_ms"]
    print(
        f"고객 과업 벤치마크 — {tasks['passed']}/{tasks['total']} 과업, "
        f"{checks['passed']}/{checks['total']} 검증"
    )
    print(
        f"기존 capability acceptance — "
        f"{capability['met']}/{capability['total']}"
    )
    print(
        f"ASGI HTTP 지연 — median {latency['median']} ms, "
        f"p95 {latency['p95']} ms\n"
    )
    for scenario in payload["scenarios"]:
        mark = "✓" if scenario["passed"] else "✗"
        print(
            f"  {mark} {scenario['id']}  {scenario['metric']:<22} "
            f"{scenario['latency_ms']:>8.2f} ms  {scenario['title']}"
        )
        for check in scenario["checks"]:
            if not check["passed"]:
                print(
                    f"      ✗ {check['name']}: "
                    f"expected={check['expected']!r}, actual={check['actual']!r}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable JSON report",
    )
    args = parser.parse_args()
    payload = report_as_dict(run_benchmark())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _text_report(payload)
    return 0 if all(item["passed"] for item in payload["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
