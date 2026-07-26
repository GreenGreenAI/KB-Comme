"""Validate documentation metadata and local Markdown links."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"
REQUIRED_METADATA = {"status", "owner", "reviewers", "last-reviewed"}
ALLOWED_STATUSES = {"draft", "proposed", "accepted", "deprecated", "superseded"}
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def parse_metadata(path: Path, text: str) -> tuple[dict[str, str], list[str]]:
    if path == DOCS_ROOT / "README.md" or "templates" in path.parts:
        return {}, []
    if not text.startswith("---\n"):
        return {}, ["missing YAML metadata block"]

    closing_index = text.find("\n---\n", 4)
    if closing_index == -1:
        return {}, ["metadata block is not closed"]

    metadata: dict[str, str] = {}
    for line in text[4:closing_index].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    errors = [
        f"missing metadata field: {key}"
        for key in sorted(REQUIRED_METADATA - metadata.keys())
    ]
    status = metadata.get("status")
    if status and status not in ALLOWED_STATUSES:
        errors.append(f"unsupported status: {status}")
    return metadata, errors


def validate_links(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().strip("<>")
        if (
            not target
            or target.startswith(("#", "http://", "https://", "mailto:"))
        ):
            continue

        target_without_fragment = target.split("#", 1)[0].split("?", 1)[0]
        candidate = (path.parent / unquote(target_without_fragment)).resolve()
        try:
            candidate.relative_to(PROJECT_ROOT)
        except ValueError:
            errors.append(f"link leaves repository: {target}")
            continue
        if not candidate.exists():
            errors.append(f"broken local link: {target}")
    return errors


def main() -> int:
    errors: list[str] = []
    markdown_files = sorted(DOCS_ROOT.rglob("*.md"))

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(PROJECT_ROOT)
        _, metadata_errors = parse_metadata(path, text)
        link_errors = validate_links(path, text)
        errors.extend(f"{relative_path}: {error}" for error in metadata_errors)
        errors.extend(f"{relative_path}: {error}" for error in link_errors)

    if errors:
        print("Documentation checks failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Documentation checks passed ({len(markdown_files)} files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
