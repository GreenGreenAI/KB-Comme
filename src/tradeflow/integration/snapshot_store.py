"""Creating snapshot files.

A snapshot is the record that a calculation was performed against a particular
view of the world, so this module treats the stored bytes as evidence rather
than as a cache: the payload is kept exactly as the source returned it, and a
second collection that disagrees with an existing file is refused instead of
overwriting it.

Reading is not here. Every layer that consumes a snapshot needs it and none of
them may import `integration`, so locating, reading and verifying live in
`domain.snapshot_file` (ADR-0005). Collectors live alongside this module;
nothing outside `integration` imports either (ADR-0003).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from tradeflow.domain.snapshot import SnapshotRef
from tradeflow.domain.snapshot_file import content_hash, safe_segment, snapshot_path


class SnapshotConflictError(RuntimeError):
    """Raised when a version is re-collected with different content."""


def build_envelope(
    *,
    source_id: str,
    version: str,
    observed_at: datetime,
    retrieved_at: datetime,
    payload: Any,
) -> dict[str, Any]:
    """Wrap a raw payload with the identity a future reader needs.

    Building the reference here means a naive timestamp or a missing version is
    rejected before anything reaches disk.
    """
    ref = SnapshotRef(
        source_id=source_id,
        version=version,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        content_hash=content_hash(payload),
    )
    if ref.observed_at > ref.retrieved_at:
        raise ValueError("observed_at cannot be later than retrieved_at")
    safe_segment(ref.source_id, "source_id")
    safe_segment(ref.version, "version")
    return {
        "source_id": ref.source_id,
        "version": ref.version,
        "observed_at": ref.observed_at.isoformat(),
        "retrieved_at": ref.retrieved_at.isoformat(),
        "content_hash": ref.content_hash,
        "payload": payload,
    }


def write_snapshot(root: Path | str, envelope: dict[str, Any]) -> Path:
    """Persist an envelope, refusing to silently replace differing content.

    Re-collecting the same version with the same payload is a no-op, so a
    collector can be re-run safely. Re-collecting it with *different* payload
    raises: a past result cites this version, and rewriting it underneath that
    citation would break the reproducibility the version exists to provide.
    """
    path = snapshot_path(root, envelope["source_id"], envelope["version"])

    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("content_hash") == envelope["content_hash"]:
            return path
        raise SnapshotConflictError(
            f"{path} already holds different content "
            f"({existing.get('content_hash')} != {envelope['content_hash']}); "
            "collect under a new version instead of replacing it"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path
