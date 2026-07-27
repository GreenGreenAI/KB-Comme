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

from tradeflow.agent.orchestrator import Analysis

FORMULA_VERSION = "exposure.v1+scenario.v1+hedge.v1"


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
    return {
        "summary": "",
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
        "risk_findings": [],
        "filing_obligations": [],
        "support_candidates": [],
        "excluded_candidates": [],
        "required_documents": [],
        "next_actions": [],
        "missing_information": list(analysis.report.missing_information()),
        "evidence": _evidence(analysis),
        "review_required": analysis.review_required,
        "review_reasons": list(analysis.review_reasons),
        "workers": {
            "completed": list(analysis.report.completed),
            "failed": analysis.report.failed,
            "skipped": analysis.report.skipped,
        },
        "calculation_versions": {
            "snapshot_version": (
                analysis.snapshot.version if analysis.snapshot else None
            ),
            "formula_version": FORMULA_VERSION,
            "rule_version": None,
        },
    }
