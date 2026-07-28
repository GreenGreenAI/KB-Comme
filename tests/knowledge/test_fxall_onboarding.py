import json
import unittest

from scripts.check_fxall_onboarding import REQUIREMENTS, readiness


class FxallOnboardingReadinessTests(unittest.TestCase):
    def test_external_requirements_are_explicit_and_no_secret_values_exist(self) -> None:
        payload = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))
        ready, incomplete = readiness(payload)
        self.assertFalse(ready)
        self.assertIn("CORPORATE_INTEGRATION_SPEC", incomplete)
        self.assertIn("LIQUIDITY_ENTITLEMENTS", incomplete)
        serialized = json.dumps(payload).lower()
        self.assertNotIn("password=", serialized)
        self.assertNotIn("private_key", serialized)

    def test_only_all_complete_is_live_ready(self) -> None:
        payload = json.loads(REQUIREMENTS.read_text(encoding="utf-8"))
        completed = {
            **payload,
            "requirements": [
                {**item, "status": "complete"}
                for item in payload["requirements"]
            ],
        }
        self.assertEqual((True, ()), readiness(completed))


if __name__ == "__main__":
    unittest.main()
