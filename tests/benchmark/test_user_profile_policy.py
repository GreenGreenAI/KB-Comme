import unittest

from .profile_policy_harness import load_baseline, run_benchmark


class UserProfilePolicyBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = run_benchmark()
        cls.baseline = load_baseline()

    def test_scenario_success_does_not_fall_below_baseline(self) -> None:
        rate = self.report.scenarios_passed / len(self.report.outcomes)
        self.assertGreaterEqual(
            rate,
            self.baseline["minimum_scenario_success_rate"],
        )

    def test_check_success_does_not_fall_below_baseline(self) -> None:
        rate = self.report.checks_passed / self.report.checks_total
        self.assertGreaterEqual(
            rate,
            self.baseline["minimum_check_success_rate"],
        )

    def test_every_critical_scenario_passes(self) -> None:
        outcomes = {item.scenario_id: item for item in self.report.outcomes}
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


if __name__ == "__main__":
    unittest.main()
