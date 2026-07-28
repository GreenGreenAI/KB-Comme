import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.record_domain_rulepack_review import record_domain_review
from tradeflow.knowledge.validation import load_promotion_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = PROJECT_ROOT / "knowledge" / "reviews" / "rulepack_promotion.json"


class DomainReviewRecordingTests(unittest.TestCase):
    def test_external_evidence_is_hashed_and_manifest_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "rulepack_promotion.json"
            manifest.write_text(MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")
            evidence = root / "expert-response.pdf"
            evidence.write_bytes(b"independent expert response")

            result = record_domain_review(
                project_root=PROJECT_ROOT,
                manifest_path=manifest,
                pack_id="FX_COMPLIANCE_MVP",
                decision="approved",
                reviewer="Independent Reviewer",
                organization="Independent FX Authority",
                authority_basis="Authorized foreign-exchange regulation reviewer",
                evidence_path=evidence,
                commit_sha="a" * 40,
                reviewed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
            )

            specs = load_promotion_manifest(PROJECT_ROOT, manifest)
            approval = next(
                item
                for spec in specs
                if spec.pack_id == "FX_COMPLIANCE_MVP"
                for item in spec.approvals
                if item.role == "domain_expert"
            )
            self.assertEqual("approved", approval.status)
            self.assertEqual(
                "Independent FX Authority",
                approval.reviewer_organization,
            )
            self.assertEqual(result["evidence_content_hash"], approval.evidence_content_hash)
            self.assertNotIn(str(evidence), manifest.read_text(encoding="utf-8"))

    def test_missing_external_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                record_domain_review(
                    project_root=PROJECT_ROOT,
                    manifest_path=Path(directory) / "manifest.json",
                    pack_id="FX_COMPLIANCE_MVP",
                    decision="approved",
                    reviewer="Reviewer",
                    organization="Authority",
                    authority_basis="Authorized",
                    evidence_path=Path(directory) / "missing.pdf",
                    commit_sha="a" * 40,
                    reviewed_at=datetime.now(timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
