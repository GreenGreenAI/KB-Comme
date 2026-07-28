"""Check that curated official web sources still contain verified markers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datetime import UTC, datetime

from tradeflow.integration.snapshot_store import build_envelope, write_snapshot
from tradeflow.integration.source_monitor import (
    check_all,
    parse_monitor_specs,
    report_json,
    verification_payload,
)
from tradeflow.tools.source_freshness import SOURCE_ID


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "knowledge" / "source_monitors.json"
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"


def source_verification_version(moment: datetime) -> str:
    """Return a collision-resistant, filesystem-safe identity for one run."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("source verification time must include a timezone")
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--write",
        action="store_true",
        help="persist the run as a snapshot the runtime can read",
    )
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    specs = parse_monitor_specs(manifest)
    selected = set(args.source_id)
    if selected:
        known = {item.source_id for item in specs}
        unknown = selected - known
        if unknown:
            parser.error("unknown source IDs: " + ", ".join(sorted(unknown)))
        specs = tuple(item for item in specs if item.source_id in selected)

    results = check_all(specs)

    if args.write:
        if selected:
            parser.error(
                "--write requires the full manifest: a partial run would "
                "record the unchecked sources as if they had no verdict"
            )
        now = datetime.now(UTC)
        path = write_snapshot(
            args.snapshot_root,
            build_envelope(
                source_id=SOURCE_ID,
                version=source_verification_version(now),
                observed_at=now,
                retrieved_at=now,
                payload=verification_payload(results),
            ),
        )
        print(f"wrote {path}")

    if args.json:
        print(report_json(results))
    else:
        for result in results:
            print(
                f"{result.status:22} {result.source_id} "
                f"HTTP {result.http_status} {result.content_length} bytes"
            )
            for marker in result.missing_markers:
                print(f"  missing marker: {marker}")
    return 1 if any(item.status != "verified" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
