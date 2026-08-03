"""The routing floor as data, so the report can count it too.

`test_routing_coverage.py` asserts it; this returns it. Same table, same
pipeline — a second implementation of the check would be a second thing to
keep true.
"""

from __future__ import annotations

from tests.acceptance.test_routing_coverage import CASES, _plan


def check_all() -> list[tuple[bool, str]]:
    """One (held, description) per routing case."""
    outcomes: list[tuple[bool, str]] = []
    for case in CASES:
        plan = _plan(case)
        missing = [w for w in case["must_plan"] if w not in plan["planned"]]
        led = (
            case["must_lead"] is None
            or plan["section_order"][0] == case["must_lead"]
        )
        outcomes.append(
            (
                not missing and led,
                f"{case['id']}  {case['why']}"
                + (f" — 빠진 워커: {', '.join(missing)}" if missing else "")
                + ("" if led else f" — 앞선 구역: {plan['section_order'][0]}"),
            )
        )
    return outcomes
