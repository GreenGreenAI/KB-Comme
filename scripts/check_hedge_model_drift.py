"""Compare a champion's current validation report with an approved baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeflow.knowledge.hedge_model_monitoring import (
    HedgeModelMonitoringStore,
    assess_model_drift,
)
from tradeflow.knowledge.hedge_model_policy import HedgeModelGovernanceRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_PATH = PROJECT_ROOT / "knowledge" / "hedge_model_registry.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a governed hedge model degrades from its baseline."
    )
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = json.loads(args.current.read_text(encoding="utf-8"))
    model_id = args.model_id or HedgeModelGovernanceRegistry.from_json(
        GOVERNANCE_PATH
    ).champion_model_id
    assessment = assess_model_drift(
        baseline,
        current,
        model_id=model_id,
    )
    document = assessment.to_json()
    if args.store:
        document["record"] = HedgeModelMonitoringStore(args.store).record(
            assessment
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(document, ensure_ascii=False, indent=2))
    return 0 if assessment.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
