"""Run the five scenarios through the real pipeline, in process.

No HTTP and no language model. The capabilities are read from the response
contract, so the score is the same whether or not a key is present — which is
the point: §4.2[9] writes the sentence, and this measures what the sentence
would have to be about.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.response import build_response
from tradeflow.domain.enums import TradeDirection
from tradeflow.knowledge.hedge_quotes import (
    HedgeQuoteSide,
    UserForwardQuote,
    UserQuoteHedgeAvailabilityService,
)
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


def _money(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _measures(scenario: dict[str, Any], program: Any) -> tuple[Any, ...]:
    """The scenario's bank quote, scoped the way the web layer scopes it."""
    quote = scenario.get("forward_quote")
    if not quote:
        return ()
    evaluated_at = datetime.combine(AS_OF, time(0, 0), tzinfo=UTC)
    net = sum(
        case.amount if case.direction is TradeDirection.EXPORT else -case.amount
        for case in program.cases
    )
    confirmed = UserForwardQuote(
        quote_id="USERQUOTE-ACCEPTANCE",
        provider_id="BANK_acceptance",
        company_id=program.company.company_id,
        case_ids=tuple(case.case_id for case in program.cases),
        base_currency=program.cases[0].currency,
        counter_currency="KRW",
        side=HedgeQuoteSide.SELL if net > 0 else HedgeQuoteSide.BUY,
        notional=abs(net),
        contract_rate=Decimal(quote["contract_rate"]),
        cost_rate=Decimal(quote["cost_rate"]),
        settlement_date=max(case.expected_payment_date for case in program.cases),
        quoted_at=evaluated_at,
        valid_until=datetime.fromisoformat(quote["valid_until"] + "T23:59:00+00:00"),
        confirmed=bool(quote["confirmed"]),
    )
    return UserQuoteHedgeAvailabilityService(
        quotes=(confirmed,),
        evaluated_at=evaluated_at,
        selected_quote_id=confirmed.quote_id,
    ).assemble(program=program, as_of=AS_OF).measures


def run(scenario: dict[str, Any]) -> Outcome:
    reading = intake(
        [scenario["case"]],
        company=DEMO.profile() if scenario.get("signed_in") else None,
        as_of=AS_OF,
    )
    if not reading.ready:
        result: dict[str, Any] = {}
    else:
        profit = scenario.get("profit") or {}
        result = build_response(
            analyze(
                reading.program,
                snapshot_root=SNAPSHOT_ROOT,
                baseline_profit=_money(profit.get("baseline_profit")),
                profit_floor=_money(profit.get("profit_floor")),
                hedge_measures=_measures(scenario, reading.program),
                utterance=scenario["utterance"],
                # Pinned, like everything else here. Left to the wall clock the
                # freshness policy eventually calls the fixture snapshot stale
                # and the market worker stops — so the score fell from 17 to 14
                # because a day passed, not because anything changed.
                as_of=datetime.combine(AS_OF, time(0, 0), tzinfo=UTC),
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
