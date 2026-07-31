"""What each agent layer read, decided and handed on, for one sentence.

    python scripts/trace.py "8월 25일 수입 6만 달러를 상계로 처리하는데 신고 대상인가요"

The response already showed the *result* of every layer — the plan, the
workers, the packet. What it never showed was the flow, so finding out why a
fact never reached the rules meant reading the code. This prints the same
record the `trace` switch puts on the wire, in the order the request moved
through it.

Reads no network and needs no key: every layer below §4.2[9] is deterministic,
and §4.2[9] only phrases what they produced.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tradeflow.agent.intake import intake  # noqa: E402
from tradeflow.agent.orchestrator import analyze  # noqa: E402
from tradeflow.agent.response import build_response  # noqa: E402
from tradeflow.domain.models import CompanyProfile  # noqa: E402
from tradeflow.domain.snapshot_file import (  # noqa: E402
    SnapshotNotFoundError,
    latest_snapshot_path,
    read_snapshot,
)
from tradeflow.runtime import narration  # noqa: E402
from tradeflow.tools.intent import read_intent  # noqa: E402
from tradeflow.tools.utterance import (  # noqa: E402
    financing_purpose,
    payment_structure,
    read_utterance,
)
from tradeflow.tools.utterance_kind import read_kind  # noqa: E402

SNAPSHOTS = ROOT / "data" / "snapshots"

#: A signed-in small exporter with no credit issues, so §5.4's rules have
#: something to read. Stated here rather than taken from the account store: the
#: point is to watch the layers, not to depend on a seeded database.
COMPANY = CompanyProfile(
    company_id="COMPANY-TRACE",
    name="추적용 기업",
    is_sme=True,
    attributes={"company.size": "small", "company.credit_issue_free": True},
)


def _observed() -> date | None:
    """The day the newest rate snapshot was observed, if there is one."""
    try:
        ref, _ = read_snapshot(latest_snapshot_path(SNAPSHOTS, "ECOS_USD_KRW"))
    except (SnapshotNotFoundError, OSError, ValueError):
        return None
    return ref.observed_at.date()


def show(title: str, rows: list[tuple[str, object]]) -> None:
    print(f"\n\033[1m{title}\033[0m")
    for label, value in rows:
        if value in ((), [], {}, "", None):
            value = "—"
        print(f"  {label:<14} {value}")


def main(argv: list[str]) -> int:
    said = argv[1] if len(argv) > 1 else "10월 24일 수출 10만 달러인데 받을 수 있는 지원제도가 있나요"
    as_of = date.fromisoformat(argv[2]) if len(argv) > 2 else date.today()
    moment = datetime.combine(as_of, time(0, 0), tzinfo=UTC)

    print(f"\n\033[2m말한 것\033[0m  {said}\n\033[2m기준일\033[0m   {as_of}")

    # A reference day before the data is as unusable as one long after it, and
    # the error says only "stale" for both. Someone reading a market worker
    # fail on freshness will look for old data; when the cause is a date they
    # typed, nothing on screen says so.
    observed = _observed()
    if observed and as_of < observed:
        print(
            f"\033[33m  주의\033[0m    스냅샷은 {observed}자입니다. 기준일이 그보다 "
            "이르면 §4.2[4]가 미래 데이터로 보고 시장 워커를 멈춥니다.\n"
            "          날짜 인자를 빼면 오늘로 봅니다."
        )

    heard = read_utterance(said, as_of=as_of)
    topics = read_intent(said)
    show(
        "1. 발화 읽기  tools/",
        [
            ("종류", read_kind(said, heard=heard, topics=topics)),
            ("주제", " · ".join(topics)),
            ("슬롯", heard),
            ("자금 용도", financing_purpose(said)),
            ("거래 구조", payment_structure(said)),
        ],
    )

    reading = intake([dict(heard)], company=COMPANY, as_of=as_of)
    show(
        "2. 인테이크  §4.2[1]",
        [
            ("준비됨", reading.ready),
            ("없는 슬롯", " · ".join(reading.missing)),
            ("되묻기", " / ".join(reading.questions)),
        ],
    )
    if not reading.ready:
        print("\n  거래가 덜 채워져 여기서 멈춥니다. 슬롯을 채우면 아래 계층이 이어집니다.\n")
        return 0

    analysis = analyze(
        reading.program,
        snapshot_root=SNAPSHOTS,
        utterance=said,
        as_of=moment,
    )
    plan = analysis.plan.as_dict()
    show(
        "3. 오케스트레이터  §4.2[2]",
        [("부를 워커", " · ".join(plan["planned"]))]
        + [
            (f"  ✗ {item['worker']}", item["reason"])
            for item in plan["workers"]
            if not item["run"]
        ]
        + [("구역 순서", " → ".join(plan["section_order"]))],
    )

    show(
        "4. 워커 실행  §9.3",
        [("완료", " · ".join(analysis.report.completed))]
        + [(f"  ✗ {name}", reason) for name, reason in analysis.report.failed.items()]
        + [
            ("소요(초)", ", ".join(f"{k} {v}" for k, v in analysis.report.took.items())),
        ],
    )

    result = build_response(analysis)
    packet = analysis.decision_packet
    show(
        "5. 지식 판정  §5.4 · §5.5",
        [
            ("선언한 구조", dict(analysis.declared_structure)),
            ("규칙 판정", len(packet.decisions) if packet else 0),
            ("지원제도 후보", len(result["support_candidates"])),
            ("신고 검토", len(result["risk_findings"])),
            ("증거", len(result["evidence"])),
        ],
    )

    show(
        "6. 답  §4.2[9] · runtime/narration",
        [(f"  {n + 1}", line) for n, line in enumerate(
            narration.support(result)
            + narration.compliance(result)
            + narration.actions(result)
        )],
    )
    print(f"\n\033[2m패킷\033[0m  {result['packet_id']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
