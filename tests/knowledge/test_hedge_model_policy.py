import json
import tempfile
import unittest
from pathlib import Path

from tradeflow.knowledge.hedge_model_policy import (
    HedgeModelGovernanceRegistry,
)
from tradeflow.tools.hedge_models import (
    CHAMPION_MODEL_ID,
    default_hedge_model_registry,
)


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "knowledge" / "hedge_model_registry.json"


class HedgeModelGovernanceRegistryTests(unittest.TestCase):
    def test_registry_matches_executable_models_and_marks_data_blocker(self) -> None:
        governance = HedgeModelGovernanceRegistry.from_json(REGISTRY_PATH)
        executable = default_hedge_model_registry()
        operational = {
            model_id
            for model_id, model in governance.models.items()
            if model.status != "data_blocked"
        }

        self.assertEqual(CHAMPION_MODEL_ID, governance.champion_model_id)
        self.assertEqual(set(executable.models), operational)
        self.assertEqual(
            60,
            governance.models[CHAMPION_MODEL_ID].parameters["window"],
        )
        blocked = governance.models["minimum_variance_forward"]
        self.assertEqual("data_blocked", blocked.status)
        self.assertTrue(blocked.blockers)
        self.assertEqual("not_applicable", blocked.scenario_centering)
        self.assertEqual(
            ["zero", "not_applicable"],
            governance.promotion_policy["allowed_scenario_centering"],
        )
        self.assertFalse(
            governance.fallback_policy["automatic_challenger_fallback"]
        )
        self.assertEqual(
            3,
            len(governance.promotion_policy["required_approvals"]),
        )

    def test_registry_rejects_implicit_fallback(self) -> None:
        document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        document["fallback_policy"]["automatic_challenger_fallback"] = True

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fallback"):
                HedgeModelGovernanceRegistry.from_json(path)

    def test_registry_rejects_unreferenced_model(self) -> None:
        document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        document["models"][1]["references"] = []

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "references"):
                HedgeModelGovernanceRegistry.from_json(path)


if __name__ == "__main__":
    unittest.main()
