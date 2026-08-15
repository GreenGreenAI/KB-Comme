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

    def test_nothing_here_greets(self) -> None:
        """인사는 모델이 씁니다.

        이 자리에 「안녕하세요 …」 한 문장이 있었고, 그것이 모든 인사에 대한
        답이었습니다. 인사는 내용이 없는 말이라 규칙에서 조립할 것이 없고,
        조립할 수 없는 문장을 여기 두면 같은 인사에 같은 문장을 낭독하는 일이
        됩니다. 모델이 없을 때는 인사 대신 이게 무엇인지 말합니다 — 정보가
        줄어드는 쪽이 아니라 느는 쪽으로 무너집니다."""
        self.assertFalse(hasattr(introduction, "opening"))


def said_once(text: str) -> str:
    return text


if __name__ == "__main__":
    unittest.main()
