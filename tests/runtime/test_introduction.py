import unittest

from tradeflow.runtime import coverage, introduction


class ParagraphTests(unittest.TestCase):
    """"뭘 할 수 있어?" has an answer already in the code. Writing it as prose
    would be the fourth place the same claim lives, and the first to go stale —
    a description outlives the rule it describes, and then the product promises
    something it stopped doing."""

    def test_it_names_the_bodies_that_actually_have_rules(self) -> None:
        said = introduction.paragraph()
        self.assertIn("한국무역보험공사", said)
        self.assertIn("한국은행", said)

    def test_it_carries_its_own_limits(self) -> None:
        """A product that describes itself without them is answering a
        different question than the one asked."""
        self.assertIn(coverage.statement("support"), said_once(introduction.paragraph()))

    def test_it_does_not_promise_what_it_cannot_predict(self) -> None:
        self.assertIn("환율을 예측하지는 않습니다", introduction.paragraph())

    def test_a_greeting_gets_a_greeting_not_a_capability_list(self) -> None:
        """Answering a greeting with the paragraph is the same mistake as
        answering it with three questions; it just takes longer to read."""
        opening = introduction.opening()
        self.assertTrue(opening.startswith("안녕하세요"))
        self.assertNotIn("· ", opening)
        self.assertLess(len(opening), len(introduction.paragraph()))


def said_once(text: str) -> str:
    return text


if __name__ == "__main__":
    unittest.main()
