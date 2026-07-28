"""Reading recorded source verifications into the freshness the rules need.

The rule engine decides a source's status before it looks at any condition, so
a source it cannot vouch for makes every rule that cites it fail closed. That
is the correct default — the alternative is asserting Korean FX-filing rules
from a version of the law nobody checked — but it means the verification result
has to actually reach the engine, and this module is that path.

Two absences are kept apart on purpose:

- **STALE** — we fetched the page and the markers that identify the enacted
  version were gone. The source really did change under us.
- **absent from the mapping** — we never got an answer, so the engine falls
  back to `FRESHNESS_UNKNOWN`.

Both stop automatic judgement, but they are different claims, and the answer
tells the user which one happened. Reporting an unreachable server as STALE
would assert a change we never observed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef
from tradeflow.domain.snapshot_file import (
    SnapshotNotFoundError,
    latest_snapshot_path,
    read_snapshot,
)

SOURCE_ID = "KNOWLEDGE_SOURCES"

#: Statutes and agency guidance move on a scale of months, not minutes, but a
#: verification that is itself months old says nothing about today's text.
DEFAULT_POLICY = FreshnessPolicy(
    max_observation_age=timedelta(days=30),
    max_retrieval_age=timedelta(days=30),
)

VERIFIED = "verified"
CHANGED = "changed_or_unavailable"


class VerificationUnavailableError(RuntimeError):
    """Raised when no usable verification snapshot exists.

    Callers are expected to let this stop the knowledge worker rather than
    substituting an optimistic default: the whole point of the check is that
    "we did not verify" must never be spelled the same way as "verified".
    """


def freshness_from_payload(
    payload: Any,
    *,
    as_of: datetime,
    ref: SnapshotRef,
    policy: FreshnessPolicy = DEFAULT_POLICY,
) -> dict[str, Freshness]:
    """Project one verification run onto per-source freshness."""
    if policy.evaluate(ref, as_of) is not Freshness.FRESH:
        raise VerificationUnavailableError(
            f"source verification {ref.version} is older than the policy allows "
            f"(observed {ref.observed_at.isoformat()}); re-run "
            "scripts/check_sources.py --write"
        )

    results = payload.get("results") if isinstance(payload, Mapping) else None
    if not isinstance(results, list):
        raise VerificationUnavailableError(
            "verification snapshot has no results list"
        )

    freshness: dict[str, Freshness] = {}
    for item in results:
        if not isinstance(item, Mapping):
            continue
        source_id = item.get("source_id")
        status = item.get("status")
        if not isinstance(source_id, str):
            continue
        if status == VERIFIED:
            freshness[source_id] = Freshness.FRESH
        elif status == CHANGED:
            freshness[source_id] = Freshness.STALE
        # Anything else — an unreachable host, a status a future collector
        # introduces — is left out, so the engine reports FRESHNESS_UNKNOWN
        # instead of a verdict we did not earn.
    return freshness


def load_source_verification(
    root: Path | str,
    *,
    as_of: datetime,
    policy: FreshnessPolicy = DEFAULT_POLICY,
) -> tuple[SnapshotRef, dict[str, Freshness]]:
    """Read the latest verification snapshot, keeping its identity.

    The reference travels with the freshness because the verification decides
    whether the rules judge at all, which makes it part of what an answer has
    to record to be reproducible (§6.2).
    """
    try:
        path = latest_snapshot_path(root, SOURCE_ID)
    except (SnapshotNotFoundError, FileNotFoundError) as exc:
        raise VerificationUnavailableError(
            f"no source verification snapshot under {root}; run "
            "scripts/check_sources.py --write"
        ) from exc

    ref, payload = read_snapshot(path)
    return ref, freshness_from_payload(
        payload, as_of=as_of, ref=ref, policy=policy
    )


def load_source_freshness(
    root: Path | str,
    *,
    as_of: datetime,
    policy: FreshnessPolicy = DEFAULT_POLICY,
) -> dict[str, Freshness]:
    """Read the latest verification snapshot under `root`."""
    _ref, freshness = load_source_verification(root, as_of=as_of, policy=policy)
    return freshness
