import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tradeflow.knowledge.hedge_model_monitoring import (
    HedgeModelMonitoringStore,
    assess_model_drift,
)


def report() -> dict:
    return {
        "benchmark": {
            "window": 250,
            "horizon_business_days": 20,
            "step": 20,
            "quote_basis": "observed_forward_quote",
        },
        "models": {
            "champion": {
                "tested": 120,
                "failed": 0,
                "scenario_centering": "zero",
                "adverse_calibration_error": 0.01,
                "floor_breach_rate": 0.02,
                "expected_shortfall": "100",
                "mean_quantile_loss": "2",
                "ratio_turnover": "0.02",
            }
        },
    }


class HedgeModelMonitoringTests(unittest.TestCase):
    def test_like_for_like_stable_run_is_healthy(self) -> None:
        baseline = report()
        current = deepcopy(baseline)
        current["models"]["champion"]["expected_shortfall"] = "105"

        assessment = assess_model_drift(
            baseline,
            current,
            model_id="champion",
        )

        self.assertTrue(assessment.healthy)
        self.assertFalse(assessment.blockers)

    def test_material_regressions_are_all_reported(self) -> None:
        baseline = report()
        current = deepcopy(baseline)
        model = current["models"]["champion"]
        model["failed"] = 2
        model["adverse_calibration_error"] = 0.05
        model["floor_breach_rate"] = 0.04
        model["expected_shortfall"] = "125"
        model["mean_quantile_loss"] = "2.4"
        model["ratio_turnover"] = "0.09"

        assessment = assess_model_drift(
            baseline,
            current,
            model_id="champion",
        )

        self.assertEqual("degraded", assessment.status)
        self.assertGreaterEqual(len(assessment.blockers), 7)
        self.assertIn(
            "absolute adverse calibration error exceeds policy",
            assessment.blockers,
        )

    def test_incompatible_benchmark_is_rejected(self) -> None:
        baseline = report()
        current = deepcopy(baseline)
        current["benchmark"]["horizon_business_days"] = 60

        with self.assertRaisesRegex(ValueError, "horizon_business_days"):
            assess_model_drift(
                baseline,
                current,
                model_id="champion",
            )

    def test_assessments_are_content_addressed_and_deduplicated(self) -> None:
        assessment = assess_model_drift(
            report(),
            report(),
            model_id="champion",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = HedgeModelMonitoringStore(Path(directory) / "models.db")
            first = store.record(assessment)
            second = store.record(assessment)

        self.assertEqual(first["assessment_hash"], second["assessment_hash"])


if __name__ == "__main__":
    unittest.main()
