import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from tradeflow.knowledge.hedge_model_promotion import (
    HedgeModelPromotionStore,
    content_hash,
)


class HedgeModelPromotionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = HedgeModelPromotionStore(self.root / "governance.db")

    def report(self, *, eligible: bool = True, quote_basis: str = "observed_forward_quote"):
        return {
            "snapshot": {"source_id": "TEST", "version": "v1"},
            "benchmark": {"quote_basis": quote_basis},
            "models": {
                "champion": {
                    "tested": 100,
                    "promotion": None,
                },
                "challenger": {
                    "tested": 100,
                    "promotion": {
                        "eligible": eligible,
                        "blockers": [] if eligible else ["economic gate failed"],
                        "champion_id": "champion",
                        "challenger_id": "challenger",
                    },
                },
            },
        }

    def test_identical_reports_are_deduplicated_by_canonical_hash(self) -> None:
        first = self.store.record_validation(self.report())
        second = self.store.record_validation(self.report())

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(content_hash(self.report()), first["content_hash"])

    def test_spot_proxy_and_failed_gates_cannot_open_a_request(self) -> None:
        spot = self.store.record_validation(
            self.report(quote_basis="spot_proxy")
        )
        failed = self.store.record_validation(self.report(eligible=False))

        with self.assertRaisesRegex(ValueError, "observed historical"):
            self.store.request_promotion("challenger", spot["run_id"])
        with self.assertRaisesRegex(ValueError, "economic gate failed"):
            self.store.request_promotion("challenger", failed["run_id"])

    def test_all_three_hash_bound_approvals_are_required(self) -> None:
        validation = self.store.record_validation(self.report())
        request = self.store.request_promotion(
            "challenger", validation["run_id"]
        )
        request_id = request["request_id"]

        first = self.store.approve(
            request_id,
            role="knowledge_domain",
            reviewer="knowledge-reviewer",
        )
        second = self.store.approve(
            request_id,
            role="platform_runtime",
            reviewer="runtime-reviewer",
        )
        self.assertFalse(first["ready"])
        self.assertFalse(second["ready"])
        with self.assertRaisesRegex(ValueError, "organization"):
            self.store.approve(
                request_id,
                role="domain_expert",
                reviewer="expert",
            )
        complete = self.store.approve(
            request_id,
            role="domain_expert",
            reviewer="expert",
            organization="Independent FX Advisory",
        )
        self.assertTrue(complete["ready"])
        self.assertTrue(
            all(
                item["validation_hash"] == validation["content_hash"]
                for item in complete["approvals"]
            )
        )

    def test_ready_request_atomically_switches_registry_champion(self) -> None:
        validation = self.store.record_validation(self.report())
        request_id = self.store.request_promotion(
            "challenger", validation["run_id"]
        )["request_id"]
        for role, reviewer, organization in (
            ("knowledge_domain", "knowledge", None),
            ("platform_runtime", "runtime", None),
            ("domain_expert", "expert", "Independent FX Advisory"),
        ):
            self.store.approve(
                request_id,
                role=role,
                reviewer=reviewer,
                organization=organization,
                now=datetime(2026, 7, 29, tzinfo=UTC),
            )
        registry_path = self.root / "registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "champion_model_id": "champion",
                    "models": [
                        {"model_id": "champion", "status": "champion"},
                        {"model_id": "challenger", "status": "challenger"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        promoted = self.store.promote(request_id, registry_path)
        registry = json.loads(registry_path.read_text(encoding="utf-8"))

        self.assertEqual("promoted", promoted["status"])
        self.assertEqual("challenger", registry["champion_model_id"])
        self.assertEqual(
            ["challenger", "champion"],
            [item["status"] for item in registry["models"]],
        )


if __name__ == "__main__":
    unittest.main()
