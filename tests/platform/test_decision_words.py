import unittest

from tests.acceptance.harness import AS_OF, DEMO, SNAPSHOT_ROOT
from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.response import build_response


def _candidates() -> list[dict]:
    reading = intake(
        [
            {
                "direction": "수출",
                "amount": "100000",
                "expected_payment_date": "2026-10-24",
            }
        ],
        company=DEMO.profile(),
        as_of=AS_OF,
    )
    return build_response(
        analyze(
            reading.program,
            snapshot_root=SNAPSHOT_ROOT,
            utterance="받을 수 있는 지원제도가 있나요",
        )
    )["support_candidates"]


class RuleWordsSurviveTests(unittest.TestCase):
    """The rulepack writes every condition in the words a company uses —
    「중소·중견기업」, 「공식 안내의 공통 이용제한 사유 없음」 — and evaluation
    was keeping only the comparison that produced it. The answer could show
    `company.size=small in ['small', 'mid_sized']` and nothing else."""

    def test_each_condition_arrives_in_its_own_words(self) -> None:
        fx = next(c for c in _candidates() if "환변동보험" in c["title"])
        said = {check["description"] for check in fx["checks"]}

        self.assertIn("중소·중견기업", said)
        self.assertIn("공식 안내의 공통 이용제한 사유 없음", said)

    def test_a_check_says_whether_it_passed_or_is_still_open(self) -> None:
        guarantee = next(c for c in _candidates() if "수출신용보증" in c["title"])
        by_word = {c["description"]: c["status"] for c in guarantee["checks"]}

        self.assertEqual("passed", by_word["수출 거래"])
        self.assertEqual("uncertain", by_word["공식 안내의 보증대상 자금"])

    def test_the_title_names_the_product_not_the_rule(self) -> None:
        """A rulepack title ends in 후보 because that is what the rule
        produces; the company wants the name of what it might apply for."""
        for candidate in _candidates():
            with self.subTest(title=candidate["title"]):
                self.assertFalse(candidate["title"].endswith("후보"))

    def test_sources_are_named_rather_than_counted(self) -> None:
        """「출처 2건」 is not a citation. §6.1 asks that a judgement show what
        it rests on, and the registry already holds the title and the link."""
        fx = next(c for c in _candidates() if "환변동보험" in c["title"])
        titles = {source["title"] for source in fx["sources"]}

        self.assertIn("환변동보험(공통) 이용요건", titles)
        for source in fx["sources"]:
            self.assertEqual("한국무역보험공사", source["organization"])
            self.assertTrue(source["url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
