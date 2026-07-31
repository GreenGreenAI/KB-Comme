"""The floor a router may add to and may not remove from.

§4.2[2] plans by keyword today, and the spec says the LLM takes the routing
decision over once there is something to route. When that happens every
keyword test in `tests/platform/` stops meaning anything — they pin the
mechanism, and the mechanism is what changes.

This pins the outcome instead. Whatever decides the plan, a company that asks
about 제작 자금 must have the eligibility worker in it, and a company that says
상계 must have the filing worker in it. A router that reads better than the
keywords will pass this; one that quietly stops calling a worker will not.

The asymmetry is the whole reason it exists. Inventing is loud — a wrong number
is on the screen. Omitting is silent: an unrun worker writes nothing, and the
reader never learns the judgement existed.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import analyze
from tradeflow.tools.intent import read_intent
from tradeflow.tools.utterance import financing_purpose, payment_structure

from .harness import AS_OF, DEMO, SNAPSHOT_ROOT

CASES = json.loads(
    (Path(__file__).parent / "routing.json").read_text(encoding="utf-8")
)["cases"]

#: Which worker answers which subject. A subject with no worker — a greeting,
#: a question about the product — is not routed and is not here.
WORKER_FOR = {
    "support": "support",
    "compliance": "compliance",
    "hedge": "hedge",
    "exposure": "exposure",
    "market_scenario": "market_scenario",
}


def _plan(case: dict) -> dict:
    reading = intake([case["case"]], company=DEMO.profile(), as_of=AS_OF)
    analysis = analyze(
        reading.program,
        snapshot_root=SNAPSHOT_ROOT,
        utterance=case["utterance"],
        as_of=None,
    )
    return analysis.plan.as_dict()


class RoutingCoverageTests(unittest.TestCase):
    def test_every_named_worker_is_in_the_plan(self) -> None:
        for case in CASES:
            with self.subTest(case=case["id"], why=case["why"]):
                planned = _plan(case)["planned"]
                for worker in case["must_plan"]:
                    self.assertIn(
                        worker,
                        planned,
                        f"{case['id']}: {case['why']}\n"
                        f"  물은 것: {case['utterance']}\n"
                        f"  계획된 것: {planned}\n"
                        f"  라우터는 이 목록에 더할 수는 있어도 뺄 수는 없습니다.",
                    )

    def test_the_subject_asked_about_leads_the_answer(self) -> None:
        """Ordering, not narrowing. `intent.py` fixes that distinction and this
        keeps a router honest about it: the section asked for comes first, and
        every other section still exists."""
        for case in CASES:
            if not case["must_lead"]:
                continue
            with self.subTest(case=case["id"]):
                order = _plan(case)["section_order"]
                self.assertEqual(
                    case["must_lead"],
                    order[0],
                    f"{case['id']}: 물은 주제가 답의 앞에 오지 않았습니다 — {order}",
                )

    def test_nothing_is_dropped_when_a_subject_is_named(self) -> None:
        """A router that answered only what was asked would be a search engine.
        §4.2[6] draws that line, and §2's reader does not know their own
        exposure well enough to ask about it."""
        for case in CASES:
            with self.subTest(case=case["id"]):
                order = _plan(case)["section_order"]
                self.assertEqual(
                    sorted(WORKER_FOR),
                    sorted(order),
                    f"{case['id']}: 구역이 빠졌습니다 — {order}",
                )

    def test_the_facts_a_sentence_states_are_read(self) -> None:
        """Routing on a fact nobody read is routing on nothing. §5.5 ran for
        the first time today only because 「상계」 started being read."""
        for case in CASES:
            wanted = case["must_read"]
            if not wanted:
                continue
            with self.subTest(case=case["id"]):
                if "financing_purpose" in wanted:
                    self.assertEqual(
                        wanted["financing_purpose"],
                        financing_purpose(case["utterance"]),
                    )
                for field in wanted.get("payment_structure", []):
                    self.assertIn(field, payment_structure(case["utterance"]))

    def test_a_sentence_that_names_no_subject_reorders_nothing(self) -> None:
        """R5 describes a trade and asks nothing. Reordering on no evidence
        would make the answer arrive differently each time for no stated
        reason."""
        plain = next(case for case in CASES if case["must_lead"] is None)

        self.assertEqual((), read_intent(plain["utterance"]))
        self.assertFalse(_plan(plain)["reordered"])


if __name__ == "__main__":
    unittest.main()
