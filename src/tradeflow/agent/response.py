"""Assembling the response contract (§7) from what the workers produced.

Every number here is copied from a tool's output. Nothing is recomputed,
rounded again or rephrased as an approximation — §9.3 requires the figures in
the answer to equal the figures the tools returned, and the way to guarantee
that is to never do arithmetic on this side of the boundary.

The one field a language model may write is `summary`. It is left empty here
and filled in by synthesis, which receives these same figures and may not
change them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from tradeflow.agent.orchestrator import FORMULA_VERSION, Analysis
from tradeflow.runtime.analysis_service import decision_packet_document
from tradeflow.runtime.sources import cite

def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _market_scenario(analysis: Analysis) -> dict[str, Any] | None:
    band = analysis.band
    if band is None:
        return None
    return {
        "spot_rate": str(band.spot_rate),
        "band_lower": str(band.lower),
        "band_upper": str(band.upper),
        "adverse_rate": str(
            band.lower
            if analysis.cashflow["net_exposure"][0]["amount"] > 0
            else band.upper
        ),
        "adverse_cashflow_change": _decimal(
            analysis.adverse_cashflow_change
        ),
        "adverse_cashflow_amount": _decimal(
            analysis.adverse_cashflow_amount
        ),
        "adverse_cashflow_direction": analysis.adverse_cashflow_direction,
        "volatility_annualized": band.volatility.annualized,
        "horizon_business_days": band.horizon_business_days,
        "confidence_level": band.confidence_level,
        "observation_days": band.volatility.window,
        "observed_from": band.volatility.first_observed.isoformat(),
        "observed_to": band.volatility.last_observed.isoformat(),
        "unit": band.unit,
        "rounding": band.rounding,
        "drift": "0 고정",
    }


#: What a rulepack title says about itself and the reader does not need.
_RULE_SUFFIXES = (" 후보", " 검토")


def _product_name(title: str) -> str:
    """The rule's title with its own bookkeeping removed."""
    for suffix in _RULE_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)]
    return title


def _engaged(decision: dict[str, Any], declared: Mapping[str, bool]) -> bool:
    """Whether the company's own words put this rule in play.

    A declared fact is established, so it never appears in `missing_fields`;
    what it does appear in is the satisfied condition the rule reports. That
    is the signal, and it needs no list of which rule belongs to which family —
    the rulepack already says so by naming the field.
    """
    if not declared:
        return False
    reasons = " ".join(decision.get("reasons") or ())
    return any(f"{field}=" in reasons for field in declared)


def _knowledge_projection(analysis: Analysis) -> dict[str, Any]:
    packet = analysis.decision_packet
    declared = analysis.declared_structure
    if packet is None:
        return {
            "decision_packet": None,
            "risk_findings": [],
            "filing_obligations": [],
            "support_candidates": [],
            "excluded_candidates": [],
            "required_documents": [],
            "next_actions": [],
        }

    document = decision_packet_document(packet)
    support_candidates = []
    excluded_candidates = []
    risk_findings = []
    for decision in document["decisions"]:
        outcome = decision["candidate_outcome"]
        projected = {
            "subject_id": decision["subject_id"],
            "rule_id": decision["rule_id"],
            # The product, not the rule. A rulepack title ends in 후보 or 검토
            # because that is what the rule produces; the company reading it
            # wants the name of the thing it might apply for.
            "title": _product_name(decision["title"]),
            "status": decision["status"],
            "matched": decision["matched"],
            "reasons": decision["reasons"],
            "missing_fields": decision["missing_fields"],
            "source_ids": decision["source_ids"],
            # Named rather than counted. 「출처 2건」 is not a citation.
            "sources": cite(decision["source_ids"]),
            # Each condition in the words the rulepack wrote it in, so the
            # answer can say what was checked instead of showing the
            # comparison that checked it.
            "checks": decision.get("checks") or [],
            "outcome": outcome,
        }
        if outcome.get("kind") == "support_candidate":
            (
                excluded_candidates
                if decision["matched"] is False
                else support_candidates
            ).append(projected)
        elif decision["matched"] is not False:
            # Two rules can both say 정보부족 and mean different things. One
            # knows it applies — the company said 상계 — and is waiting on the
            # detail that decides which authority. The other does not know
            # whether it applies at all, because nobody said whether there is
            # a 상호계산 account. Nineteen rules run on every compliance
            # request, so arriving as one list buries the three that were
            # answering the question.
            projected["engaged"] = _engaged(decision, declared)
            risk_findings.append(projected)

    actions = document["actions"]
    filing_obligations = [
        action
        for action in actions
        if action.get("authority") is not None
        and not action.get("product_ids")
    ]
    required_documents = list(
        dict.fromkeys(
            document_title
            for action in actions
            for document_title in action["required_documents"]
        )
    )
    return {
        "decision_packet": document,
        "risk_findings": risk_findings,
        "filing_obligations": filing_obligations,
        "support_candidates": support_candidates,
        "excluded_candidates": excluded_candidates,
        "required_documents": required_documents,
        "next_actions": actions,
    }


def _hedge_analysis(analysis: Analysis) -> dict[str, Any] | None:
    hedge = analysis.hedge
    if hedge is None:
        return None
    return {
        "optimal_ratio": hedge.optimal_ratio,
        "status": hedge.status,
        "alternatives": list(hedge.alternatives),
        "breakeven_rate": _decimal(hedge.breakeven.rate),
        "loss_probability": hedge.breakeven.loss_probability,
        "adverse_rate": str(hedge.adverse_rate),
        "confidence_level": hedge.confidence_level,
        "instrument_candidates": [{"measure_id": hedge.measure_id, "status": "available"}],
        "payoff_comparison": [
            {
                "ratio": scenario.ratio,
                "label": scenario.label,
                "points": [
                    {"label": p.label, "rate": str(p.rate), "profit": str(p.profit)}
                    for p in scenario.points
                ],
            }
            for scenario in hedge.comparison
        ],
        "rate_rounding": hedge.rate_rounding,
        "profit_rounding": hedge.profit_rounding,
    }


def _evidence(analysis: Analysis) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = [
        {
            "role": "calculation",
            "detail": "현금흐름·순노출 산출",
            "formula_version": FORMULA_VERSION,
        }
    ]
    snapshot = analysis.snapshot
    if snapshot is not None:
        records.append(
            {
                "role": "market_data",
                "source_id": snapshot.source_id,
                "version": snapshot.version,
                "observed_at": snapshot.observed_at.isoformat(),
                "retrieved_at": snapshot.retrieved_at.isoformat(),
                "content_hash": snapshot.content_hash,
            }
        )
    return records


#: The optional trade details a request may carry, so the echo can carry them
#: back. Named rather than "everything in `attributes`" — that mapping also
#: holds facts this product derived, and echoing those would invite a client to
#: send back a calculation as if the company had stated it.
ECHOED_ATTRIBUTES = frozenset(
    {
        "expected_shipment_date",
        "contract_date",
        "advance_payment_ratio",
        "counterparty_id",
    }
)


def _as_text(value: Any) -> str:
    """As the request wrote it. The slot reader parses dates and ratios on the
    way in, so echoing the parsed object would hand the client a shape its own
    request model does not accept — an echo the caller cannot resend is the
    same as no echo."""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_response(analysis: Analysis) -> dict[str, Any]:
    """Project the analysis onto the response contract, summary left blank."""
    knowledge = _knowledge_projection(analysis)
    return {
        "summary": "",
        "packet_id": (
            analysis.decision_packet.packet_id
            if analysis.decision_packet is not None
            else None
        ),
        # Everything the caller told us about each trade, echoed whole.
        #
        # The client holds the conversation and resends it, and it takes this
        # list as the authority on what the trades are — so a detail missing
        # here is a detail the next request cannot carry. It used to stop at
        # the six fields the figures need, which silently dropped the shipment
        # date on every turn: the company answered 「언제 선적하시나요」, the
        # answer reached the rules once, and the turn after that it was gone
        # and the same question came back. Forever, for anyone who kept
        # talking.
        #
        # `country` rather than `counterparty_country`: this is echoed back
        # into a request, and the request calls it `country`.
        "trade_timeline": [
            {
                "case_id": case.case_id,
                "direction": case.direction.value,
                "currency": case.currency,
                "amount": str(case.amount),
                "expected_payment_date": case.expected_payment_date.isoformat(),
                "payment_method": case.payment_method.value,
                **({"country": case.counterparty_country} if case.counterparty_country else {}),
                **{
                    field: _as_text(value)
                    for field, value in (case.attributes or {}).items()
                    if field in ECHOED_ATTRIBUTES and value not in (None, "")
                },
            }
            for case in analysis.program.cases
        ],
        "cashflow_analysis": {
            key: [
                {field: str(value) for field, value in entry.items()}
                for entry in entries
            ]
            for key, entries in analysis.cashflow.items()
        },
        "market_scenario": _market_scenario(analysis),
        "hedge_analysis": _hedge_analysis(analysis),
        **knowledge,
        "missing_information": list(analysis.report.missing_information()),
        "evidence": _evidence(analysis),
        "review_required": analysis.review_required,
        "review_reasons": list(analysis.review_reasons),
        "workers": {
            "completed": list(analysis.report.completed),
            "failed": analysis.report.failed,
            "skipped": analysis.report.skipped,
            # Timing is not here. §6.2 asks that the same analysis reproduce,
            # and the replay test compares the whole response — a duration
            # differs between two identical runs by definition. It goes to the
            # log, and to the trace switch, neither of which is the answer.
        },
        # What §5.3 is still waiting on. The profit inputs come from the
        # analysis; the quote is named here because nothing upstream can — a
        # forward rate is what one bank offered one company, so the only place
        # it can come from is the person holding it, and the screen needs to
        # know to ask. Without this the hedge section said "계산하지 않았습니다"
        # with no way for the reader to change that.
        "required_inputs": {
            "hedge": list(analysis.required_inputs),
            "quote": (
                []
                if analysis.hedge is not None
                else ["provider", "contract_rate", "cost_rate", "valid_until"]
            ),
        },
        # §4.2[2]'s output. A reader can see which workers were called and, for
        # the rest, what would call them — so an empty section is never left to
        # be read as "nothing to report".
        "execution_plan": analysis.plan.as_dict(),
        "calculation_versions": analysis.versions.as_dict(),
    }
