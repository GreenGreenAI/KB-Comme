import unittest
from unittest.mock import patch

from tradeflow.runtime import planner


class _Reply:
    def __init__(self, subjects: list[str]) -> None:
        import json

        self.choices = [
            type(
                "C",
                (),
                {"message": type("M", (), {"content": json.dumps({"subjects": subjects})})},
            )
        ]


class _Agent:
    """A synthesizer that answers with whatever it was handed."""

    available = True
    model = "test"

    def __init__(self, subjects: list[str] | Exception) -> None:
        self._subjects = subjects

    def _open(self):
        outer = self

        class Completions:
            def create(self, **_: object):
                if isinstance(outer._subjects, Exception):
                    raise outer._subjects
                return _Reply(outer._subjects)

        return type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})})()


class WideningTests(unittest.TestCase):
    """The model may add a subject; it may not remove one.

    That is `intent.py`'s rule applied to the reader — 의도는 답의 순서를
    정하지 범위를 좁히지 않는다. A reading that could drop 신고의무 from a
    question about 환율 would reopen the hole §2 describes, where the company
    does not know what to ask about.
    """

    def test_it_adds_what_the_keywords_missed(self) -> None:
        widened = planner.widen(
            "지금 환전해 두는 게 나을까요", (), synthesizer=_Agent(["hedge"])
        )

        self.assertEqual(("hedge",), widened)

    def test_it_cannot_remove_what_the_keywords_read(self) -> None:
        widened = planner.widen(
            "상계로 처리하는데 신고 대상인가요",
            ("compliance",),
            synthesizer=_Agent(["hedge"]),
        )

        self.assertIn("compliance", widened)

    def test_the_keyword_reading_keeps_its_lead(self) -> None:
        """Every routing case pinned in routing.json is asserted against the
        keyword reading. If the model could re-rank, those would hold or fail
        depending on what a model said that day."""
        widened = planner.widen(
            "환율이 떨어지면 손해인가요",
            ("market_scenario",),
            synthesizer=_Agent(["support", "compliance"]),
        )

        self.assertEqual("market_scenario", widened[0])

    def test_a_subject_outside_the_vocabulary_is_dropped(self) -> None:
        widened = planner.widen("무엇이든", (), synthesizer=_Agent(["환율", "hedge"]))

        self.assertEqual(("hedge",), widened)

    def test_a_failed_call_leaves_the_keywords_standing(self) -> None:
        """No key, no network, a malformed reply — the product answered before
        this existed and must go on answering."""
        widened = planner.widen(
            "환율이 떨어지면", ("market_scenario",), synthesizer=_Agent(RuntimeError("down"))
        )

        self.assertEqual(("market_scenario",), widened)

    def test_an_empty_sentence_is_not_sent(self) -> None:
        with patch.object(planner, "Synthesizer") as built:
            self.assertEqual((), planner.widen("", ()))
            self.assertEqual((), planner.widen(None, ()))
        built.assert_not_called()


if __name__ == "__main__":
    unittest.main()
