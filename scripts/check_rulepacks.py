"""Validate golden cases and fail-closed rulepack promotion declarations."""

from __future__ import annotations

import argparse
from pathlib import Path

from tradeflow.knowledge.validation import (
    audit_rulepack_readiness,
    load_promotion_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "knowledge" / "reviews" / "rulepack_promotion.json"
DEFAULT_SOURCES = PROJECT_ROOT / "knowledge" / "source_registry.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    try:
        specs = load_promotion_manifest(PROJECT_ROOT, args.manifest)
    except (OSError, TypeError, ValueError) as exc:
        print(f"integrity error: {exc}")
        return 1

    reports = []
    audit_failed = False
    for spec in specs:
        try:
            reports.append(
                audit_rulepack_readiness(
                    project_root=PROJECT_ROOT,
                    source_registry_path=DEFAULT_SOURCES,
                    spec=spec,
                )
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            print(f"integrity error: {spec.pack_id}: {exc}")
            audit_failed = True
    for report in reports:
        state = "ready" if report.ready else "draft"
        boundary_label = (
            "boundary"
            if report.validation.boundary_count == 1
            else "boundaries"
        )
        print(
            f"{state:8} {report.pack_id}: "
            f"{report.validation.case_count} cases, "
            f"{report.validation.boundary_count} {boundary_label}, "
            f"{report.validation.rule_count} rules"
        )
        for issue in report.integrity_issues:
            print(f"  integrity: {issue}")
        for blocker in report.blockers:
            print(f"  blocker: {blocker}")

    if audit_failed or any(report.integrity_issues for report in reports):
        return 1
    if args.require_ready and any(not report.ready for report in reports):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
