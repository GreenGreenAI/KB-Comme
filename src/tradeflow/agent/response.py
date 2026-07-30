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

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from tradeflow.agent.orchestrator import FORMULA_VERSION, Analysis
from tradeflow.agent.routing import COMPLIANCE, DECLARED_STRUCTURE_FIELDS
from tradeflow.knowledge.compliance_declarations import DECLARABLE_GATEWAY_FIELDS
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


SOURCE_REGISTRY = Path(__file__).resolve().parents[3] / "knowledge" / "source_registry.json"


@lru_cache(maxsize=1)
def _source_registry() -> dict[str, dict[str, Any]]:
    document = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    return {item["source_id"]: item for item in document["sources"]}


def _evidence(
    analysis: Analysis,
    knowledge: dict[str, Any],
) -> list[dict[str, Any]]:
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
    source_ids = {
        source_id
        for decision in (knowledge.get("decision_packet") or {}).get("decisions", [])
        for source_id in decision.get("source_ids", [])
    }
    registry = _source_registry()
    for source_id in sorted(source_ids):
        source = registry.get(source_id)
        if source is None:
            records.append(
                {
                    "role": "official_source",
                    "source_id": source_id,
                    "verified": False,
                    "status": "registry_missing",
                }
            )
            continue
        records.append(
            {
                "role": "official_source",
                "source_id": source_id,
                "title": source.get("title"),
                "organization": source.get("organization"),
                "url": source.get("url"),
                "official": source.get("official"),
                "verified": source.get("verified"),
                "retrieved_at": source.get("retrieved_at"),
                "effective_from": source.get("effective_from"),
                "effective_to": source.get("effective_to"),
                "content_hash": source.get("content_hash"),
            }
        )
    return records


def _input_scope(field: str) -> str:
    if field in {"baseline_profit", "profit_floor", "forward_quote"}:
        return "hedge"
    if field.startswith("company."):
        return "profile"
    if field in DECLARABLE_GATEWAY_FIELDS:
        return "compliance_declaration"
    if field in {
        "trade.payment_term_days",
        "financing.purpose",
        "financing.has_bank_consultation",
    }:
        return "case"
    return "external_evidence"


def _missing_input_queue(
    analysis: Analysis,
    knowledge: dict[str, Any],
) -> list[dict[str, Any]]:
    """One ordered queue across workers, without converting unknown to false."""
    queued: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()

    packet = knowledge.get("decision_packet") or {}
    for decision in packet.get("decisions", []):
        if decision.get("status") != "insufficient_information":
            continue
        for field in decision.get("missing_fields", []):
            key = (decision.get("subject_id"), field)
            if key in seen:
                continue
            seen.add(key)
            queued.append(
                {
                    "field": field,
                    "scope": _input_scope(field),
                    "subject_id": decision.get("subject_id"),
                    "worker": (
                        "support"
                        if decision.get("outcome", decision.get("candidate_outcome", {})).get(
                            "kind"
                        )
                        == "support_candidate"
                        else "compliance"
                    ),
                    "status": decision.get("status"),
                    "reason": decision.get("title"),
                }
            )

    for worker in analysis.plan.decisions:
        required = (
            DECLARED_STRUCTURE_FIELDS
            if worker.name == COMPLIANCE and not worker.run and not worker.requires
            else worker.requires
        )
        for field in required:
            key = (None, field)
            if key in seen:
                continue
            seen.add(key)
            queued.append(
                {
                    "field": field,
                    "scope": _input_scope(field),
                    "subject_id": None,
                    "worker": worker.name,
                    "status": "missing",
                    "reason": worker.reason,
                }
            )
    priority = {
        "profile": 0,
        "compliance_declaration": 1,
        "hedge": 2,
        "case": 3,
        "external_evidence": 4,
    }
    return sorted(
        queued,
        key=lambda item: (
            priority.get(item["scope"], 9),
            item["subject_id"] or "",
            item["field"],
        ),
    )


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
        "company_profile": {
            "company_id": analysis.program.company.company_id,
            "company_name": analysis.program.company.name,
            "is_sme": analysis.program.company.is_sme,
            "country_code": analysis.program.company.country_code,
            "industry_code": analysis.program.company.industry_code,
            "facts": {
                key: value
                for key, value in analysis.program.company.facts().items()
                if value is not None
            },
        },
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
        "evidence": _evidence(analysis, knowledge),
        "review_required": analysis.review_required,
        "review_reasons": list(analysis.review_reasons),
        "workers": {
            "completed": list(analysis.report.completed),
            "failed": analysis.report.failed,
            "skipped": analysis.report.skipped,
        },
        "missing_input_queue": _missing_input_queue(analysis, knowledge),
        "required_inputs": {
            "hedge": list(analysis.required_inputs),
            "quote": (
                []
                if analysis.hedge is not None
                else ["provider", "contract_rate", "cost_rate", "valid_until"]
            ),
            "all": [
                item["field"]
                for item in _missing_input_queue(analysis, knowledge)
            ],
        },
        # §4.2[2]'s output. A reader can see which workers were called and, for
        # the rest, what would call them — so an empty section is never left to
        # be read as "nothing to report".
        "execution_plan": analysis.plan.as_dict(),
        "calculation_versions": analysis.versions.as_dict(),
    }
