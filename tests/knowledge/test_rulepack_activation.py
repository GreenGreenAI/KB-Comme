import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.promote_rulepacks import promote
from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.validation import rulepack_review_hash


class RulepackActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "packs").mkdir()
        (self.root / "suites").mkdir()
        self.pack_path = self.root / "packs" / "test.json"
        self.suite_path = self.root / "suites" / "test.json"
        self.pack = {
            "schema_version": "1.0",
            "pack_id": "TEST",
            "status": "draft",
            "rules": [
                {
                    "rule_id": "R1",
                    "production_ready": False,
                    "conditions": [],
                    "candidate_outcome": {"kind": "support_candidate"},
                }
            ],
        }
        self.suite = {"schema_version": "1.0", "cases": [{"case_id": "C1"}]}
        self.pack_path.write_text(json.dumps(self.pack), encoding="utf-8")
        self.suite_path.write_text(json.dumps(self.suite), encoding="utf-8")

    def manifest(self, *, pending: str | None = None) -> Path:
        approvals = []
        for role in ("knowledge_domain", "platform_runtime", "domain_expert"):
            if role == pending:
                approvals.append({"role": role, "status": "pending"})
            else:
                approvals.append(
                    {
                        "role": role,
                        "status": "approved",
                        "rulepack_hash": rulepack_review_hash(self.pack),
                        "validation_suite_hash": content_hash(self.suite),
                    }
                )
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "rulepacks": [
                        {
                            "pack_id": "TEST",
                            "rulepack_path": "packs/test.json",
                            "validation_suite_path": "suites/test.json",
                            "approvals": approvals,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_activation_metadata_does_not_change_reviewed_content_hash(self) -> None:
        active = {
            **self.pack,
            "status": "active",
            "rules": [{**self.pack["rules"][0], "production_ready": True}],
        }
        self.assertEqual(
            rulepack_review_hash(self.pack),
            rulepack_review_hash(active),
        )

    def test_complete_approvals_activate_every_rule_together(self) -> None:
        promote(
            project_root=self.root,
            manifest_path=self.manifest(),
            pack_id="TEST",
        )
        promoted = json.loads(self.pack_path.read_text(encoding="utf-8"))

        self.assertEqual("active", promoted["status"])
        self.assertTrue(all(rule["production_ready"] for rule in promoted["rules"]))

    def test_pending_expert_blocks_activation(self) -> None:
        with self.assertRaisesRegex(ValueError, "domain_expert"):
            promote(
                project_root=self.root,
                manifest_path=self.manifest(pending="domain_expert"),
                pack_id="TEST",
            )
        self.assertEqual(
            "draft",
            json.loads(self.pack_path.read_text(encoding="utf-8"))["status"],
        )


if __name__ == "__main__":
    unittest.main()
