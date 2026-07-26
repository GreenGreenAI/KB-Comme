"""Reading and writing snapshot files.

A snapshot is the record that a calculation was performed against a particular
view of the world, so this module treats the stored bytes as evidence rather
than as a cache: the payload is kept exactly as the source returned it, the
hash is verified on the way back in, and a second collection that disagrees
with an existing file is refused instead of overwriting it.

Collectors live alongside this module; nothing outside `integration` imports
either (ADR-0003).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tradeflow.domain.snapshot import SnapshotRef

# Both values become path segments, so keep them to characters that cannot
# escape the snapshot root.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SnapshotConflictError(RuntimeError):
    """Raised when a version is re-collected with different content."""


class SnapshotIntegrityError(RuntimeError):
    """Raised when a stored payload no longer matches its recorded hash."""


def canonical_json(payload: Any) -> str:
    """Serialize a payload so that equal payloads always hash equally."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(payload: Any) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _safe_segment(value: str, field: str) -> str:
    if not _SAFE_SEGMENT.match(value):
        raise ValueError(
            f"{field} must be a plain path segment, got {value!r}"
        )
    return value


def snapshot_path(root: Path | str, source_id: str, version: str) -> Path:
    return (
        Path(root)
        / _safe_segment(source_id, "source_id")
        / f"{_safe_segment(version, 'version')}.json"
    )


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
    _safe_segment(ref.source_id, "source_id")
    _safe_segment(ref.version, "version")
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


def read_snapshot(path: Path | str) -> tuple[SnapshotRef, Any]:
    """Load an envelope, verifying it is the snapshot it claims to be."""
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = envelope["payload"]

    recorded = envelope["content_hash"]
    actual = content_hash(payload)
    if recorded != actual:
        raise SnapshotIntegrityError(
            f"{path}: payload does not match recorded hash "
            f"({recorded} != {actual})"
        )

    ref = SnapshotRef(
        source_id=envelope["source_id"],
        version=envelope["version"],
        observed_at=datetime.fromisoformat(envelope["observed_at"]),
        retrieved_at=datetime.fromisoformat(envelope["retrieved_at"]),
        content_hash=recorded,
    )
    return ref, payload
