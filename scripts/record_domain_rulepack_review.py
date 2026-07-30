"""Record an independent expert decision without storing its sensitive source."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.validation import (
    PromotionApproval,
    load_promotion_manifest,
    rulepack_review_hash,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "knowledge" / "reviews" / "rulepack_promotion.json"


def record_domain_review(
    *,
    project_root: Path,
    manifest_path: Path,
    pack_id: str,
    decision: str,
    reviewer: str,
    organization: str,
    authority_basis: str,
    evidence_path: Path,
    commit_sha: str,
    reviewed_at: datetime,
) -> dict:
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    if not evidence_path.is_file():
        raise ValueError("expert evidence file does not exist")
    evidence_hash = "sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(
        (item for item in manifest["rulepacks"] if item["pack_id"] == pack_id),
        None,
    )
    if entry is None:
        raise ValueError(f"unknown rulepack: {pack_id}")
    pack = json.loads(
        (project_root / entry["rulepack_path"]).read_text(encoding="utf-8")
    )
    suite = json.loads(
        (project_root / entry["validation_suite_path"]).read_text(encoding="utf-8")
    )
    approval = PromotionApproval(
        role="domain_expert",
        status=decision,
        reviewer=reviewer.strip(),
        reviewed_at=reviewed_at,
        commit_sha=commit_sha,
        rulepack_hash=rulepack_review_hash(pack),
        validation_suite_hash=content_hash(suite),
        reviewer_organization=organization.strip(),
        authority_basis=authority_basis.strip(),
        evidence_content_hash=evidence_hash,
    )
    document = {
        "role": approval.role,
        "status": approval.status,
        "reviewer": approval.reviewer,
        "reviewed_at": approval.reviewed_at.isoformat(),
        "commit_sha": approval.commit_sha,
        "rulepack_hash": approval.rulepack_hash,
        "validation_suite_hash": approval.validation_suite_hash,
        "reviewer_organization": approval.reviewer_organization,
        "authority_basis": approval.authority_basis,
        "evidence_content_hash": approval.evidence_content_hash,
    }
    entry["approvals"] = [
        document if item["role"] == "domain_expert" else item
        for item in entry["approvals"]
    ]
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # Parse the complete candidate before replacing the governed manifest.
    load_promotion_manifest(project_root, temporary)
    temporary.replace(manifest_path)
    return document


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack_id")
    parser.add_argument("--decision", choices=("approved", "rejected"), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--authority-basis", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commit-sha", default=_head())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    result = record_domain_review(
        project_root=PROJECT_ROOT,
        manifest_path=args.manifest,
        pack_id=args.pack_id,
        decision=args.decision,
        reviewer=args.reviewer,
        organization=args.organization,
        authority_basis=args.authority_basis,
        evidence_path=args.evidence,
        commit_sha=args.commit_sha,
        reviewed_at=datetime.now(UTC),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
