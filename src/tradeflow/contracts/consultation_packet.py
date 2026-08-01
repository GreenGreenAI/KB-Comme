"""A bank-neutral handoff contract built from a verified analysis result.

The packet is the boundary between TradeFlow and a bank channel.  It contains
the decision facts an RM needs, but never raw uploaded document bytes.  A bank
adapter may later transmit this exact contract; the demo deliberately stops at
an auditable manual download.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"


def build_consultation_packet(
    *,
    run_id: str,
    analysis_created_at: str,
    consented_at: str,
    result: Mapping[str, Any],
    requested_by: str,
    target_bank: str = "KB_KOOKMIN_BANK",
) -> dict[str, Any]:
    """Project an analysis into the minimum bank-consultation payload."""
    material = {
        "run_id": run_id,
        "packet_id": result.get("packet_id"),
        "target_bank": target_bank,
        "schema_version": SCHEMA_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]

    cashflow = result.get("cashflow_analysis") or {}
    required_documents = sorted(
        {
            document
            for action in result.get("next_actions") or []
            for document in action.get("required_documents") or []
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "packet_type": "decision_passport",
        "handoff_id": f"HANDOFF-{digest}",
        "state": "ready_for_manual_handoff",
        "channel": {
            "target_bank": target_bank,
            "mode": "manual_packet",
            "adapter_contract": "bank_consultation.v1",
        },
        "consent": {
            "confirmed": True,
            "requested_by": requested_by,
            "confirmed_at": consented_at,
            "purpose": "trade_finance_consultation",
        },
        "analysis": {
            "run_id": run_id,
            "decision_packet_id": result.get("packet_id"),
            "created_at": analysis_created_at,
            "review_required": bool(result.get("review_required")),
            "review_reasons": result.get("review_reasons") or [],
        },
        "customer": result.get("company_profile") or {},
        "trades": result.get("trade_timeline") or [],
        "liquidity": {
            "net_exposure": cashflow.get("net_exposure") or [],
            "funding_gap": cashflow.get("funding_gap") or [],
            "natural_hedge_amount": cashflow.get("natural_hedge_amount") or [],
            "events": cashflow.get("events") or [],
        },
        "decisions": {
            "support_candidates": result.get("support_candidates") or [],
            "filing_obligations": result.get("filing_obligations") or [],
            "risk_findings": result.get("risk_findings") or [],
            "next_actions": result.get("next_actions") or [],
            "missing_inputs": result.get("missing_input_queue") or [],
        },
        "decision_experience": {
            "next_decisive_questions": (
                result.get("next_decisive_questions") or []
            ),
            "decision_delta": result.get("decision_delta"),
        },
        "document_checklist": required_documents,
        "evidence": result.get("evidence") or [],
        "calculation_versions": result.get("calculation_versions") or {},
        "privacy": {
            "raw_document_content_included": False,
            "transmission_performed": False,
        },
    }


@dataclass(frozen=True)
class ManualBankConsultationHandoffProvider:
    """Default adapter: create a downloadable packet and transmit nothing."""

    def prepare(
        self,
        *,
        run_id: str,
        analysis_created_at: str,
        consented_at: str,
        result: Mapping[str, Any],
        requested_by: str,
        target_bank: str,
    ) -> dict[str, Any]:
        return build_consultation_packet(
            run_id=run_id,
            analysis_created_at=analysis_created_at,
            consented_at=consented_at,
            result=result,
            requested_by=requested_by,
            target_bank=target_bank,
        )
