import unittest

from .capabilities import BY_NAME
from .harness import run_all

#: What the system reaches today, scenario by scenario. This is a ratchet, not
#: a target: a change that lowers any of these numbers has taken a judgement
#: away from the user, and should say so out loud rather than slipping through
#: green. Raising one means updating the line here, which is the moment to ask
#: whether it was raised by adding knowledge or by loosening a check.
BASELINE = {"S1": 6, "S2": 4, "S3": 1, "S4": 4, "S5": 2}


class ScenarioTests(unittest.TestCase):
    def test_no_scenario_loses_ground(self) -> None:
        for outcome in run_all():
            with self.subTest(scenario=outcome.scenario):
                self.assertGreaterEqual(
                    len(outcome.met),
                    BASELINE[outcome.scenario],
                    f"{outcome.scenario} 이 낮아졌습니다: 없음 = {outcome.missing}",
                )

    def test_every_gap_says_what_would_close_it(self) -> None:
        """A missing capability with no `needs` is a complaint, not a work
        item. The harness exists to hand A a list, so an unexplained gap is a
        defect in the harness itself."""
        for outcome in run_all():
            for name in outcome.missing:
                with self.subTest(scenario=outcome.scenario, capability=name):
                    self.assertTrue(BY_NAME[name].needs)

    def test_a_missing_fact_is_never_read_as_a_capability(self) -> None:
        """§5.4 reports both the conditions it evaluated and the ones it went
        without. Counting the second kind would report progress that did not
        happen — the first version of this harness scored country risk as met
        because a rule said `missing fact: counterparty.country_restricted`."""
        from .capabilities import satisfied

        item = {"reasons": ["missing fact: counterparty.country_restricted"]}
        self.assertEqual(satisfied(item), [])


if __name__ == "__main__":
    unittest.main()
