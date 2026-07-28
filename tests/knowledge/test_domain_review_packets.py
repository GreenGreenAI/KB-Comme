import json
import unittest

from scripts.build_rulepack_review_packets import PROJECT_ROOT, build_packet
from tradeflow.domain.snapshot_file import content_hash


class DomainReviewPacketTests(unittest.TestCase):
    def test_packet_is_hash_bound_and_covers_every_rule(self) -> None:
        pack = json.loads(
            (PROJECT_ROOT / "knowledge/rulepacks/fx_compliance_mvp.json").read_text(
                encoding="utf-8"
            )
        )
        suite = json.loads(
            (
                PROJECT_ROOT
                / "knowledge/validation_suites/fx_compliance_mvp_cases.json"
            ).read_text(encoding="utf-8")
        )
        packet = build_packet(pack, suite)

        self.assertEqual(content_hash(pack), packet["rulepack_hash"])
        self.assertEqual(content_hash(suite), packet["validation_suite_hash"])
        self.assertEqual(
            {rule["rule_id"] for rule in pack["rules"]},
            {rule["rule_id"] for rule in packet["rules"]},
        )
        self.assertTrue(
            packet["reviewer_requirements"]["independent_from_rule_author"]
        )
        for rule in packet["rules"]:
            self.assertTrue(rule["golden_expectations"])
            self.assertEqual(3, len(rule["review_questions"]))

    def test_changed_rule_invalidates_packet_hash(self) -> None:
        pack = {
            "pack_id": "P",
            "as_of": "2026-07-28",
            "rules": [],
        }
        suite = {"cases": [], "boundary_checks": []}
        original = build_packet(pack, suite)
        changed = build_packet({**pack, "as_of": "2026-07-29"}, suite)
        self.assertNotEqual(original["rulepack_hash"], changed["rulepack_hash"])


if __name__ == "__main__":
    unittest.main()
