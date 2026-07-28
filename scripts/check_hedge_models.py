"""Run the reproducible hedge-model benchmark on a committed FX snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.snapshot_file import read_snapshot
from tradeflow.knowledge.hedge_model_policy import (
    HedgeModelGovernanceRegistry,
)
from tradeflow.tools.fx_series import usd_krw_series
from tradeflow.tools.hedge_model_validation import (
    HedgeModelPromotionPolicy,
    StressPeriod,
    assess_model_promotion,
    compare_registered_models,
)
from tradeflow.tools.hedge_models import (
    CHAMPION_MODEL_ID,
    default_hedge_model_registry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = (
    PROJECT_ROOT
    / "data"
    / "snapshots"
    / "ECOS_USD_KRW"
    / "2026-07-27.json"
)
GOVERNANCE_PATH = PROJECT_ROOT / "knowledge" / "hedge_model_registry.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate governed hedge models without lookahead."
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help="Committed ECOS USD/KRW snapshot to evaluate.",
    )
    parser.add_argument("--window", type=int, default=250)
    parser.add_argument("--horizon", type=int, default=20)
    parser.add_argument("--step", type=int, default=20)
    return parser


def main() -> int:
    args = _parser().parse_args()
    governance = HedgeModelGovernanceRegistry.from_json(GOVERNANCE_PATH)
    registry = default_hedge_model_registry()
    operational = {
        model_id
        for model_id, model in governance.models.items()
        if model.status != "data_blocked"
    }
    if set(registry.models) != operational:
        raise ValueError(
            "executable and governed hedge-model registries have drifted"
        )
    if governance.champion_model_id != CHAMPION_MODEL_ID:
        raise ValueError("governed and executable champions have drifted")
    for model_id, model in registry.models.items():
        governed = governance.models[model_id]
        if model.scenario_centering != governed.scenario_centering:
            raise ValueError(
                f"{model_id}: executable and governed scenario centering "
                "have drifted"
            )
    if tuple(
        governance.promotion_policy["allowed_scenario_centering"]
    ) != HedgeModelPromotionPolicy().allowed_scenario_centering:
        raise ValueError(
            "executable and governed scenario-centering policies have drifted"
        )

    metadata, payload = read_snapshot(args.snapshot)
    observations = usd_krw_series(payload)
    results = compare_registered_models(
        registry,
        observations,
        net_exposure=Decimal("100000"),
        baseline_profit=Decimal("50000000"),
        profit_floor=Decimal("45000000"),
        horizon_business_days=args.horizon,
        window=args.window,
        step=args.step,
        quote_basis="spot_proxy",
        stress_periods=(
            StressPeriod("pandemic", date(2020, 2, 1), date(2020, 6, 30)),
            StressPeriod(
                "dollar_surge",
                date(2022, 7, 1),
                date(2022, 12, 31),
            ),
        ),
    )
    champion = results[CHAMPION_MODEL_ID]
    report = {
        "snapshot": {
            "path": str(args.snapshot.relative_to(PROJECT_ROOT)),
            "source_id": metadata.source_id,
            "version": metadata.version,
            "observation_count": len(observations),
        },
        "benchmark": {
            "window": args.window,
            "horizon_business_days": args.horizon,
            "step": args.step,
            "quote_basis": "spot_proxy",
        },
        "models": {
            model_id: {
                "tested": result.tested,
                "failed": result.failed,
                "scenario_centering": result.scenario_centering,
                "adverse_breach_rate": result.adverse_breach_rate,
                "adverse_calibration_error": result.adverse_calibration_error,
                "floor_breach_rate": result.floor_breach_rate,
                "expected_shortfall": str(result.expected_shortfall),
                "mean_quantile_loss": str(result.mean_quantile_loss),
                "mean_ratio": str(result.mean_ratio),
                "ratio_turnover": str(result.ratio_turnover),
                "promotion": (
                    None
                    if model_id == CHAMPION_MODEL_ID
                    else {
                        "eligible": (
                            assessment := assess_model_promotion(
                                champion,
                                result,
                            )
                        ).eligible,
                        "blockers": assessment.blockers,
                    }
                ),
            }
            for model_id, result in results.items()
        },
        "data_blocked_models": {
            model_id: model.blockers
            for model_id, model in governance.models.items()
            if model.status == "data_blocked"
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(result.tested < 100 for result in results.values()):
        raise ValueError("benchmark produced fewer than 100 validation origins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
