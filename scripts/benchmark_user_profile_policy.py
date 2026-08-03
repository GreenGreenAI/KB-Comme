"""Print the executable profile-policy benchmark as text or JSON."""

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

from tests.benchmark.profile_policy_harness import (  # noqa: E402
    report_as_dict,
    run_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = report_as_dict(run_benchmark())
    scenario = payload["scenario_success"]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        checks = payload["check_success"]
        print(
            "유저 프로필·정책 벤치마크 — "
            f"{scenario['passed']}/{scenario['total']} 시나리오, "
            f"{checks['passed']}/{checks['total']} 검증"
        )
        for item in payload["scenarios"]:
            mark = "✓" if item["passed"] else "✗"
            print(f"  {mark} {item['id']} {item['track']:<26} {item['title']}")
            for check in item["checks"]:
                if not check["passed"]:
                    print(
                        f"      ✗ {check['name']}: "
                        f"expected={check['expected']!r}, actual={check['actual']!r}"
                    )
    return 0 if scenario["passed"] == scenario["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
