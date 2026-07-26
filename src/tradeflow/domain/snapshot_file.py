"""Locating, reading and verifying a snapshot file.

ADR-0003 shares data between layers as committed files rather than as running
code, which leaves one question it did not answer: which layer may open them.
Reading is placed here because every consumer needs it and `domain` is the only
layer all of them may reach (ADR-0005). Creating snapshots stays in
`integration`, where the sources live.

Nothing here touches the network. Reading a committed file is the data
dependency ADR-0003 chose; it is not an integration concern.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tradeflow.domain.snapshot import SnapshotRef

# `source_id` and `version` become path segments, so keep them to characters
# that cannot escape the snapshot root.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class SnapshotIntegrityError(RuntimeError):
    """Raised when a stored payload no longer matches its recorded hash."""


def canonical_json(payload: Any) -> str:
    """Serialize a payload so that equal payloads always hash equally."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(payload: Any) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def safe_segment(value: str, field: str) -> str:
    if not _SAFE_SEGMENT.match(value):
        raise ValueError(f"{field} must be a plain path segment, got {value!r}")
    return value


def snapshot_path(root: Path | str, source_id: str, version: str) -> Path:
    return (
        Path(root)
        / safe_segment(source_id, "source_id")
        / f"{safe_segment(version, 'version')}.json"
    )


def read_snapshot(path: Path | str) -> tuple[SnapshotRef, Any]:
    """Load an envelope, verifying it is the snapshot it claims to be.

    The hash is recomputed rather than trusted. A silently corrupted file would
    otherwise produce a different result under the same version, which is the
    one thing a version exists to rule out (§9.1).
    """
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
