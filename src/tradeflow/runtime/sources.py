"""Official sources, named the way a person would cite them.

A judgement carries `source_ids` — `KSURE_FX_INSURANCE_ELIGIBILITY` — and the
screen was reporting them by counting: 「근거 6건 · 출처 2건」. A count is not a
citation. §6.1 asks that every judgement show what it rests on, and the registry
已 holds the title, the issuing body and the official URL for each one.

Read from the registry rather than restated here, so a source that changes its
title or moves changes this too.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

REGISTRY = Path(__file__).resolve().parents[3] / "knowledge" / "source_registry.json"


@cache
def _registry() -> dict[str, dict[str, Any]]:
    try:
        loaded = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = loaded.get("sources") or []
    return {
        entry["source_id"]: entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("source_id")
    }


def cite(source_ids: tuple[str, ...] | list[str]) -> list[dict[str, str]]:
    """Title, issuer and link for each source, in the order given.

    An id the registry does not know is carried through under its own name
    rather than dropped: a judgement resting on something unregistered is worth
    seeing, and silently shortening the list would hide it.
    """
    cited: list[dict[str, str]] = []
    for source_id in source_ids:
        entry = _registry().get(source_id)
        cited.append(
            {
                "source_id": source_id,
                "title": (entry or {}).get("title") or source_id,
                "organization": (entry or {}).get("organization") or "",
                "url": (entry or {}).get("url") or "",
            }
        )
    return cited
