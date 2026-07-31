import logging
import unittest
from io import StringIO

from tradeflow.runtime import observing
from tradeflow.web.app import AnalyzeRequest, analyze_endpoint

CASE = {
    "direction": "수출",
    "amount": "100000",
    "expected_payment_date": "2026-10-24",
}


class ListenTests(unittest.TestCase):
    """§4.2[9] wrote `logger.info` on every refusal and none of it arrived.

    uvicorn does not configure application loggers, so INFO was dropped at the
    root: every synthesised sentence was rejected for a week and the only way
    to find out was to call the module by hand. A check that fails silently is
    a check nobody is running.
    """

    def setUp(self) -> None:
        self.logger = logging.getLogger(observing.ROOT)
        self.handlers = list(self.logger.handlers)
        self.logger.handlers.clear()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        self.logger.handlers.clear()
        self.logger.handlers.extend(self.handlers)

    def test_a_message_reaches_the_stream(self) -> None:
        stream = StringIO()
        observing.listen(stream)

        logging.getLogger(f"{observing.ROOT}.synthesis").info("합성 미채택: 시험")

        self.assertIn("합성 미채택: 시험", stream.getvalue())

    def test_attaching_twice_does_not_double_every_line(self) -> None:
        stream = StringIO()
        observing.listen(stream)
        observing.listen(stream)

        logging.getLogger(observing.ROOT).info("한 번")

        self.assertEqual(1, stream.getvalue().count("한 번"))


class TookTests(unittest.TestCase):
    def test_a_failure_is_still_timed(self) -> None:
        """A worker that failed after five seconds and one that failed
        immediately are different problems, and the report kept only the
        failure."""
        record: dict[str, float] = {}

        with self.assertRaises(ValueError):
            with observing.took(record, "market_scenario"):
                raise ValueError("stale")

        self.assertIn("market_scenario", record)


class TraceTests(unittest.TestCase):
    """The response showed the result of every layer and never the flow.

    Which slots intake read, which facts the orchestrator asserted, which of
    them reached the rules — finding out why `financing.purpose` was never
    filled meant reading the code, because no answer said what had been handed
    across.
    """

    def _answer(self, **body) -> dict:
        return analyze_endpoint(
            AnalyzeRequest(
                cases=[CASE],
                as_of="2026-07-28",
                company_size="small",
                credit_issue_free=True,
                **body,
            )
        )["result"]

    def test_it_is_off_unless_asked_for(self) -> None:
        """The record carries the company's own facts, and an instrument that
        ships them to every caller is a leak with a switch."""
        self.assertNotIn("trace", self._answer(utterance="지원제도가 있나요"))

    def test_it_shows_what_each_layer_read_and_handed_on(self) -> None:
        trace = self._answer(utterance="지원제도가 있나요", trace=True)["trace"]

        self.assertEqual(["support"], trace["utterance"]["intent"])
        self.assertTrue(trace["intake"]["ready"])
        self.assertIn("support", trace["plan"]["planned"])
        self.assertIn("exposure", trace["workers"]["completed"])

    def test_every_worker_that_ran_reports_how_long_it_took(self) -> None:
        trace = self._answer(utterance="지원제도가 있나요", trace=True)["trace"]

        self.assertTrue(trace["workers"]["took_seconds"])
        for seconds in trace["workers"]["took_seconds"].values():
            self.assertGreaterEqual(seconds, 0)


class ReplayTests(unittest.TestCase):
    def test_timing_is_not_part_of_the_answer(self) -> None:
        """§6.2 asks that the same analysis reproduce, and the replay test
        compares the whole response — a duration differs between two identical
        runs by definition."""
        answer = analyze_endpoint(
            AnalyzeRequest(cases=[CASE], as_of="2026-07-28")
        )["result"]

        self.assertNotIn("took", answer["workers"])


if __name__ == "__main__":
    unittest.main()
