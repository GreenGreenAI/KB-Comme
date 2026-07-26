"""Check that curated official web sources still contain verified markers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeflow.integration.source_monitor import (
    fetch_and_check,
    parse_monitor_specs,
    report_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "knowledge" / "source_monitors.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--json", action="store_true")
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

    results = tuple(fetch_and_check(spec) for spec in specs)
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
