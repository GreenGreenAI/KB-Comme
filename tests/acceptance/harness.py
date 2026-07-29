"""Run the five scenarios through the real pipeline, in process.

No HTTP and no language model. The capabilities are read from the response
contract, so the score is the same whether or not a key is present — which is
the point: §4.2[9] writes the sentence, and this measures what the sentence
would have to be about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.response import build_response
from tradeflow.runtime.accounts import Account

from .capabilities import BY_NAME

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ROOT = REPO_ROOT / "data" / "snapshots"
SCENARIOS = json.loads(
    (Path(__file__).parent / "scenarios.json").read_text(encoding="utf-8")
)["scenarios"]

#: The seeded demo company, stated here rather than read from the account
#: store: the harness must give the same answer on a machine that has never run
#: the seed script.
DEMO = Account(
    account_id="COMPANY-HANBIT",
    email="kim@hanbit.co.kr",
    company_name="한빛정밀",
    facts={
        "company.is_sme": True,
        "company.size": "small",
        "company.is_domestic": True,
        "company.credit_issue_free": True,
        "company.ksure_exporter_grade": "A",
        "company.industry_code": "C29",
    },
)

AS_OF = date(2026, 7, 28)


@dataclass(frozen=True)
class Outcome:
    scenario: str
    title: str
    met: tuple[str, ...]
    missing: tuple[str, ...]
    out_of_scope: tuple[str, ...]

    @property
    def score(self) -> str:
        wanted = len(self.met) + len(self.missing)
        return f"{len(self.met)}/{wanted}"


def run(scenario: dict[str, Any]) -> Outcome:
    reading = intake(
        [scenario["case"]],
        company=DEMO.profile() if scenario.get("signed_in") else None,
        as_of=AS_OF,
    )
    if not reading.ready:
        result: dict[str, Any] = {}
    else:
        result = build_response(
            analyze(
                reading.program,
                snapshot_root=SNAPSHOT_ROOT,
                utterance=scenario["utterance"],
            )
        )

    skip = set(scenario.get("out_of_scope", [])[:1])
    met, missing = [], []
    for name in scenario["expects"]:
        if name in skip:
            continue
        (met if BY_NAME[name].present(result) else missing).append(name)
    return Outcome(
        scenario["id"],
        scenario["title"],
        tuple(met),
        tuple(missing),
        tuple(skip),
    )


def run_all() -> list[Outcome]:
    return [run(scenario) for scenario in SCENARIOS]
