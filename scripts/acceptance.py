"""Where the five scenarios stand, and what would move them.

    python scripts/acceptance.py

Reads nothing from the network and needs no API key: the score is about which
judgements the pipeline produced, not about how the sentence reads.
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.acceptance.capabilities import BY_NAME  # noqa: E402
from tests.acceptance.harness import run_all  # noqa: E402


def main() -> int:
    outcomes = run_all()
    met = sum(len(o.met) for o in outcomes)
    wanted = sum(len(o.met) + len(o.missing) for o in outcomes)

    print(f"시나리오 수용 현황 — {met}/{wanted}\n")
    for outcome in outcomes:
        print(f"  {outcome.scenario}  {outcome.score:>5}  {outcome.title}")
        for name in outcome.missing:
            capability = BY_NAME[name]
            print(f"        ✗ {capability.what}")
            print(f"          필요: {capability.needs}")
        for name in outcome.out_of_scope:
            print(f"        — {BY_NAME[name].what} (범위 밖)")
        print()

    gaps: dict[str, list[str]] = {}
    for outcome in outcomes:
        for name in outcome.missing:
            gaps.setdefault(name, []).append(outcome.scenario)
    print("무엇을 만들면 몇 개가 열리는가\n")
    for name, scenarios in sorted(gaps.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(scenarios)}개  {BY_NAME[name].what}  ({', '.join(scenarios)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
