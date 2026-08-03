import unittest

from .kb_api_harness import load_cases, run_api_audit


class KbUserTypeApiBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()
        cls.observations = run_api_audit()

    def test_all_eight_user_types_are_exercised_over_http(self) -> None:
        self.assertEqual(8, len(self.observations))
        self.assertEqual(
            8,
            len({item.user_type for item in self.observations}),
        )
        self.assertTrue(all(item.http_status == 200 for item in self.observations))

    def test_current_required_api_capabilities_are_preserved(self) -> None:
        for observation in self.observations:
            with self.subTest(scenario=observation.scenario_id):
                self.assertTrue(
                    observation.passed,
                    observation.required_missing,
                )

    def test_each_case_retains_an_observable_api_response(self) -> None:
        for observation in self.observations:
            with self.subTest(scenario=observation.scenario_id):
                self.assertEqual("ready", observation.response["status"])
                self.assertTrue(observation.response["summary"])


if __name__ == "__main__":
    unittest.main()
