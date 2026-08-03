import unittest

from .harness import load_baseline, run_benchmark


class UserTaskBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_benchmark()
        cls.baseline = load_baseline()

    def test_task_success_does_not_fall_below_baseline(self) -> None:
        self.assertGreaterEqual(
            self.report.task_success_rate,
            self.baseline["minimum_task_success_rate"],
        )

    def test_check_success_does_not_fall_below_baseline(self) -> None:
        self.assertGreaterEqual(
            self.report.check_success_rate,
            self.baseline["minimum_check_success_rate"],
        )

    def test_every_critical_scenario_passes(self) -> None:
        outcomes = {
            item.scenario_id: item
            for item in self.report.outcomes
        }
        for scenario_id in self.baseline["required_critical_scenarios"]:
            with self.subTest(scenario=scenario_id):
                self.assertTrue(
                    outcomes[scenario_id].passed,
                    [
                        check.name
                        for check in outcomes[scenario_id].checks
                        if not check.passed
                    ],
                )

    def test_capability_acceptance_does_not_regress(self) -> None:
        self.assertGreaterEqual(
            self.report.capabilities_met,
            self.baseline["minimum_capabilities_met"],
        )


if __name__ == "__main__":
    unittest.main()
