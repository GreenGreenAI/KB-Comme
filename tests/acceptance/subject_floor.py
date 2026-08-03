"""What a sentence with no trade in it is read as being about.

`routing.json` pins the plan and needs no model, so it is a test. This needs
one: most of these sentences name none of the keyword vocabulary and the
reading is the model's. Measured in the report rather than asserted in the
suite, for two reasons.

A unit suite must pass with no key and no network. Without a model the reading
here is the keywords alone, which is a different thing and already covered.

And it is eleven live calls. Run beside every other test that makes one, a
single timeout failed the suite for a reason that had nothing to do with the
reading — which teaches people that a red suite means nothing.

The score is the point. A model that gets worse leaves the plan untouched and
the routing floor silent, because every worker still runs — only the answer
arrives in the wrong order, led by the wrong section, asking for the wrong
thing.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from tradeflow.runtime.planner import widen
from tradeflow.runtime.synthesis import Synthesizer
from tradeflow.tools.intent import read_intent

CASES = json.loads(
    (Path(__file__).parent / "subjects.json").read_text(encoding="utf-8")
)["cases"]


@lru_cache(maxsize=None)
def _read(utterance: str) -> tuple[str, ...]:
    return widen(utterance, read_intent(utterance), seed=utterance)


def check_all() -> list[tuple[bool, str]] | None:
    """One (held, description) per sentence, or None when there is no model."""
    if not Synthesizer().available:
        return None

    outcomes: list[tuple[bool, str]] = []
    for case in CASES:
        read = _read(case["utterance"])
        missing = [name for name in case["expect"] if name not in read]
        # A sentence that asks nothing must read as nothing: inventing a
        # subject reorders the answer on no evidence.
        invented = not case["expect"] and read
        led = not case.get("lead") or (read and read[0] == case["lead"])
        note = ""
        if missing:
            note = f" — 빠진 주제: {', '.join(missing)}"
        elif invented:
            note = f" — 없는 의도를 지어냄: {', '.join(read)}"
        elif not led:
            note = f" — 앞선 주제: {read[0] if read else '없음'}"
        outcomes.append(
            (not missing and not invented and led, f"{case['utterance']}{note}")
        )
    return outcomes
