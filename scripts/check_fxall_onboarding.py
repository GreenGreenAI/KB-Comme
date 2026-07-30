"""Report FXall live-connection readiness without reading or printing secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = (
    PROJECT_ROOT / "knowledge/providers/fxall_onboarding_requirements.json"
)


def readiness(payload: dict) -> tuple[bool, tuple[str, ...]]:
    incomplete = tuple(
        item["requirement_id"]
        for item in payload["requirements"]
        if item["status"] != "complete"
    )
    return not incomplete, incomplete


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="return non-zero when external onboarding is incomplete",
    )
    args = parser.parse_args()
    payload = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))
    ready, incomplete = readiness(payload)
    print(f"{payload['provider_id']}: {payload['status']}")
    for requirement_id in incomplete:
        print(f"  pending: {requirement_id}")
    if ready:
        print("  ready for authenticated live-session verification")
    return 1 if args.require_ready and not ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
