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
from typing import Any

from tradeflow.agent.orchestrator import FORMULA_VERSION, Analysis
from tradeflow.runtime.analysis_service import decision_packet_document

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


def _knowledge_projection(analysis: Analysis) -> dict[str, Any]:
    packet = analysis.decision_packet
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
            "title": decision["title"],
            "status": decision["status"],
            "matched": decision["matched"],
            "reasons": decision["reasons"],
            "missing_fields": decision["missing_fields"],
            "source_ids": decision["source_ids"],
            "outcome": outcome,
        }
        if outcome.get("kind") == "support_candidate":
            (
                excluded_candidates
                if decision["matched"] is False
                else support_candidates
            ).append(projected)
        elif decision["matched"] is not False:
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
        "trade_timeline": [
            {
                "case_id": case.case_id,
                "direction": case.direction.value,
                "currency": case.currency,
                "amount": str(case.amount),
                "expected_payment_date": case.expected_payment_date.isoformat(),
                "payment_method": case.payment_method.value,
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
