"""Fetch the snapshots that have gone stale, and only those.

    python scripts/refresh.py            # 낡은 것만 받는다
    python scripts/refresh.py --check    # 무엇이 낡았는지 보기만 한다
    python scripts/refresh.py --force    # 신선해도 다시 받는다

Every piece of this already existed. `integration/ecos.py` fetches and files a
snapshot, `collection.py` knows when a dataset is due, and the freshness policy
knows when the market worker will refuse to run. What was missing was anything
that put them together, so the snapshot sat at 7/27 until the band stopped
being produced and nobody was told.

It is a script rather than a step in the request for a reason. ADR-0003 makes
`integration` a leaf that no module may import: collection performs network I/O
and must reach the product only through the files it writes. An answer that
fetched its own data mid-request would also stop reproducing — §6.2 asks that
the same analysis re-run give the same packet, and a fetch makes the result
depend on the moment it happened.

Run it before a demo, from a scheduler, or by hand. What it must not be is
something the answer waits on.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeflow.domain.snapshot_file import (  # noqa: E402
    SnapshotNotFoundError,
    latest_snapshot_path,
    read_snapshot,
)
from tradeflow.integration import ecos  # noqa: E402

SNAPSHOTS = ROOT / "data" / "snapshots"

#: How far back to ask for. The band reads a 60-business-day window, so a fetch
#: that returned only today would leave the estimator short after any gap.
LOOKBACK_DAYS = 150

#: The same limit §4.2[4] holds the market worker to. Named from there rather
#: than repeated as a number: if the policy changes, this follows it.
from tradeflow.agent.orchestrator import FX_FRESHNESS  # noqa: E402


def age(source_id: str, now: datetime) -> tuple[str, timedelta] | None:
    """The newest snapshot's version and how old its observation is."""
    try:
        path = latest_snapshot_path(SNAPSHOTS, source_id)
    except SnapshotNotFoundError:
        return None
    ref, _ = read_snapshot(path)
    return ref.version, now - ref.observed_at


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    force = "--force" in argv
    now = datetime.now(UTC)

    current = age(ecos.SOURCE_ID, now)
    limit = FX_FRESHNESS.max_observation_age

    if current is None:
        print(f"{ecos.SOURCE_ID}: 스냅샷이 없습니다.")
        stale = True
    else:
        version, old = current
        stale = old > limit
        state = "낡음" if stale else "신선"
        print(
            f"{ecos.SOURCE_ID}: {version} · 관측 후 {old.days}일 "
            f"(한계 {limit.days}일) · {state}"
        )

    if not stale and not force:
        print("받을 것이 없습니다.")
        return 0
    if check_only:
        print("--check 이므로 받지 않았습니다.")
        return 1

    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    try:
        path = ecos.collect(SNAPSHOTS, start, end)
    except Exception as failure:  # noqa: BLE001 — a refusal must say why
        print(f"받지 못했습니다: {type(failure).__name__}: {failure}")
        print("ECOS_API_KEY 가 .env 에 있는지, 한국은행 ECOS 가 응답하는지 확인하세요.")
        return 1

    after = age(ecos.SOURCE_ID, now)
    print(f"받았습니다: {path.relative_to(ROOT)}")
    if after is not None:
        version, old = after
        print(f"이제 {version} · 관측 후 {old.days}일입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
