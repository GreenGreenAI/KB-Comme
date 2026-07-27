"""Deterministic derivation of mutual-account compliance deadlines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.compliance_dates import (
    deadline_breached,
    mutual_account_entry_deadline,
    mutual_account_settlement_deadline,
)
from tradeflow.domain.enums import EvidenceRole
from tradeflow.knowledge.facts import FactAssertion


@dataclass(frozen=True)
class MutualAccountTimeline:
    entry_basis_date: date | None = None
    entry_completed_on: date | None = None
    period_end: date | None = None
    balance_filing_completed_on: date | None = None
    balance_settlement_completed_on: date | None = None


@dataclass(frozen=True)
class MutualAccountDerivation:
    assertions: tuple[FactAssertion, ...]
    evidence: EvidenceDescriptor
    deadlines: dict[str, date]


def derive_mutual_account_timeline(
    *,
    case_id: str,
    timeline: MutualAccountTimeline,
    as_of: date,
) -> MutualAccountDerivation:
    """Calculate independent entry, filing, and settlement deadline facts."""
    facts: dict[str, bool] = {}
    deadlines: dict[str, date] = {}

    if timeline.entry_basis_date is not None:
        deadline = mutual_account_entry_deadline(timeline.entry_basis_date)
        deadlines["entry"] = deadline
        facts["payment.mutual_account.entry_deadline_breached"] = deadline_breached(
            deadline,
            as_of=as_of,
            completed_on=timeline.entry_completed_on,
        )

    if timeline.period_end is not None:
        deadline = mutual_account_settlement_deadline(timeline.period_end)
        deadlines["balance_filing"] = deadline
        deadlines["balance_settlement"] = deadline
        facts[
            "payment.mutual_account.balance_filing_deadline_breached"
        ] = deadline_breached(
            deadline,
            as_of=as_of,
            completed_on=timeline.balance_filing_completed_on,
        )
        facts[
            "payment.mutual_account.balance_settlement_deadline_breached"
        ] = deadline_breached(
            deadline,
            as_of=as_of,
            completed_on=timeline.balance_settlement_completed_on,
        )

    evidence_id = f"calculation:mutual-account:{case_id}"
    evidence = EvidenceDescriptor(
        evidence_id=evidence_id,
        role=EvidenceRole.CALCULATION,
        identifiers=(case_id, "mutual-account-deadlines"),
        generated_at=datetime.combine(as_of, time.min, tzinfo=UTC),
        payload={
            "engine": "tradeflow.mutual_account_deadlines.v1",
            "inputs": {
                "entry_basis_date": timeline.entry_basis_date,
                "entry_completed_on": timeline.entry_completed_on,
                "period_end": timeline.period_end,
                "balance_filing_completed_on": (
                    timeline.balance_filing_completed_on
                ),
                "balance_settlement_completed_on": (
                    timeline.balance_settlement_completed_on
                ),
                "as_of": as_of,
            },
            "deadlines": deadlines,
            "facts": facts,
        },
    )
    assertions = tuple(
        FactAssertion(field, value, (evidence_id,))
        for field, value in facts.items()
    )
    return MutualAccountDerivation(assertions, evidence, deadlines)
