"""Activate an approved rulepack without invalidating semantic approvals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.validation import rulepack_review_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "knowledge" / "reviews" / "rulepack_promotion.json"


def promote(
    *,
    project_root: Path,
    manifest_path: Path,
    pack_id: str,
) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    spec = next(
        (item for item in manifest["rulepacks"] if item["pack_id"] == pack_id),
        None,
    )
    if spec is None:
        raise ValueError(f"unknown rulepack: {pack_id}")
    pending = [
        item["role"]
        for item in spec["approvals"]
        if item.get("status") != "approved"
    ]
    if pending:
        raise ValueError("approvals are incomplete: " + ", ".join(pending))

    pack_path = project_root / spec["rulepack_path"]
    suite_path = project_root / spec["validation_suite_path"]
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    review_hash = rulepack_review_hash(pack)
    suite_hash = content_hash(suite)
    for approval in spec["approvals"]:
        if approval.get("rulepack_hash") != review_hash:
            raise ValueError(f"{approval['role']}: stale rulepack approval")
        if approval.get("validation_suite_hash") != suite_hash:
            raise ValueError(f"{approval['role']}: stale validation approval")

    if pack.get("status") not in {"draft", "active"}:
        raise ValueError("rulepack has an unsupported status")
    flags = [rule.get("production_ready") for rule in pack["rules"]]
    if any(not isinstance(value, bool) for value in flags):
        raise ValueError("production_ready must be boolean")
    if any(flags) and not all(flags):
        raise ValueError("partial production_ready state is forbidden")

    pack["status"] = "active"
    for rule in pack["rules"]:
        rule["production_ready"] = True
    # This assertion is the reason the semantic hash exists: activation must
    # not alter a condition, procedure, source or outcome approved by reviewers.
    if rulepack_review_hash(pack) != review_hash:
        raise ValueError("promotion changed reviewable rulepack content")

    temporary = pack_path.with_suffix(pack_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(pack_path)
    return pack_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack_id")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    path = promote(
        project_root=PROJECT_ROOT,
        manifest_path=args.manifest,
        pack_id=args.pack_id,
    )
    print(path.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
