"""Build deterministic, hash-bound packets for independent domain review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.validation import rulepack_review_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_packet(pack: dict, suite: dict) -> dict:
    expectations: dict[str, list[dict]] = {}
    for case in suite["cases"]:
        for expected in case["expectations"]:
            expectations.setdefault(expected["rule_id"], []).append(
                {
                    "case_id": case["case_id"],
                    "matched": expected["matched"],
                    "status": expected["status"],
                    "missing_fields": expected.get("missing_fields", []),
                }
            )
    boundaries: dict[str, list[dict]] = {}
    for check in suite.get("boundary_checks", []):
        boundaries.setdefault(check["rule_id"], []).append(check)

    rules = []
    for rule in pack["rules"]:
        rules.append(
            {
                "rule_id": rule["rule_id"],
                "title": rule["title"],
                "conditions": rule["conditions"],
                "candidate_outcome": rule["candidate_outcome"],
                "required_documents": rule.get("required_documents", []),
                "document_set_ids": rule.get("document_set_ids", []),
                "procedure_steps": rule["procedure_steps"],
                "source_ids": rule["source_ids"],
                "source_claim_ids": rule["source_claim_ids"],
                "review_policy": rule["review_policy"],
                "golden_expectations": expectations.get(rule["rule_id"], []),
                "boundary_checks": boundaries.get(rule["rule_id"], []),
                "review_questions": [
                    "조건과 예외가 현재 공식 기준을 빠짐없이 반영하는가?",
                    "기관·신고/신청 행위·시점·필요서류가 정확한가?",
                    "경계값과 golden case의 기대 결과가 정확한가?",
                ],
            }
        )
    return {
        "schema_version": "1.0",
        "packet_type": "independent_domain_review_request",
        "pack_id": pack["pack_id"],
        "as_of": pack["as_of"],
        "rulepack_hash": rulepack_review_hash(pack),
        "validation_suite_hash": content_hash(suite),
        "requested_decisions": ["approved", "rejected", "changes_requested"],
        "reviewer_requirements": {
            "independent_from_rule_author": True,
            "identity_and_organization_required": True,
            "authority_basis_required": True,
            "rule_by_rule_comments_required_for_non_approval": True,
        },
        "rules": rules,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "knowledge" / "reviews" / "requests",
    )
    args = parser.parse_args()
    manifest = json.loads(
        (PROJECT_ROOT / "knowledge/reviews/rulepack_promotion.json").read_text(
            encoding="utf-8"
        )
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for spec in manifest["rulepacks"]:
        pack = json.loads((PROJECT_ROOT / spec["rulepack_path"]).read_text("utf-8"))
        suite = json.loads(
            (PROJECT_ROOT / spec["validation_suite_path"]).read_text("utf-8")
        )
        packet = build_packet(pack, suite)
        target = args.output / f"{spec['pack_id'].lower()}_review_request.json"
        target.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(target.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
