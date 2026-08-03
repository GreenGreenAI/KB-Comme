"""Print real API observations for the eight KB trade-finance user types."""

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

from tests.benchmark.kb_api_harness import report_as_dict, run_api_audit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = report_as_dict(run_api_audit())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        success = payload["required_success"]
        print(
            "KB 유저 유형 API 감사 — "
            f"{success['passed']}/{success['total']} 필수 경로 통과"
        )
        for item in payload["observations"]:
            mark = "✓" if item["passed"] else "✗"
            print(f"  {mark} {item['id']} {item['user_type']}")
            print(f"      query: {item['query']}")
            print(f"      met: {', '.join(item['required_met'])}")
            print(f"      product gaps: {', '.join(item['desired_missing'])}")
    return 0 if success["passed"] == success["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
