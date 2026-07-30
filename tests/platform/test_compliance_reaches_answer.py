import unittest
from datetime import date

from tests.acceptance.harness import AS_OF, SNAPSHOT_ROOT
from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.response import build_response

UTTERANCE = "8월 25일 수입 6만 달러를 상계로 처리하는데 신고 대상인가요"


def _answer(utterance: str | None):
    reading = intake(
        [{"direction": "수입", "amount": "60000", "expected_payment_date": "2026-08-25"}],
        as_of=AS_OF,
    )
    return build_response(
        analyze(reading.program, snapshot_root=SNAPSHOT_ROOT, utterance=utterance)
    )


class ComplianceReachesTheAnswerTests(unittest.TestCase):
    """§5.5's rules had never run. The worker routes on four declarations that
    nothing filled, so every request skipped it — including the ones whose own
    sentence made the declaration."""

    def test_stating_the_structure_runs_the_rules(self) -> None:
        self.assertNotIn("compliance", _answer(UTTERANCE)["workers"]["skipped"])

    def test_saying_nothing_still_holds_the_judgement_open(self) -> None:
        """§5.5 does not conclude 신고 불필요 from silence, and reading the
        declarations must not change that."""
        self.assertIn(
            "compliance",
            _answer("8월 25일 수입 6만 달러 지급합니다")["workers"]["skipped"],
        )

    def test_the_rules_the_company_put_in_play_are_marked(self) -> None:
        """Nineteen rules run on every compliance request. Three of them know
        they apply and are waiting on which authority; the rest do not know
        whether they apply at all. As one list the three that answered the
        question were buried."""
        findings = _answer(UTTERANCE)["risk_findings"]
        engaged = [f["title"] for f in findings if f.get("engaged")]

        self.assertEqual(3, len(engaged))
        for title in engaged:
            self.assertIn("상계", title)
        self.assertGreater(len([f for f in findings if not f.get("engaged")]), 0)

    def test_nothing_is_marked_when_nothing_was_declared(self) -> None:
        for finding in _answer("8월 25일 수입 6만 달러 지급합니다")["risk_findings"]:
            self.assertFalse(finding.get("engaged"))


if __name__ == "__main__":
    unittest.main()
