"""Detect and persist governed hedge-model performance degradation."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from tradeflow.knowledge.hedge_model_promotion import canonical_json, content_hash


@dataclass(frozen=True)
class HedgeModelDriftPolicy:
    """Absolute and relative limits that trigger human investigation."""

    minimum_origins: int = 100
    maximum_failures: int = 0
    maximum_calibration_error: float = 0.03
    maximum_calibration_error_increase: float = 0.01
    maximum_floor_breach_increase: float = 0.01
    maximum_expected_shortfall_increase: float = 0.10
    maximum_quantile_loss_increase: float = 0.10
    maximum_turnover_increase: Decimal = Decimal("0.05")


@dataclass(frozen=True)
class MetricDrift:
    metric: str
    baseline: str
    current: str
    change: str
    limit: str
    breached: bool


@dataclass(frozen=True)
class HedgeModelDriftAssessment:
    model_id: str
    status: str
    baseline_hash: str
    current_hash: str
    metrics: tuple[MetricDrift, ...]
    blockers: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return self.status == "healthy"

    def to_json(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "status": self.status,
            "healthy": self.healthy,
            "baseline_hash": self.baseline_hash,
            "current_hash": self.current_hash,
            "metrics": [asdict(metric) for metric in self.metrics],
            "blockers": list(self.blockers),
        }


def _decimal(model: dict[str, Any], field: str) -> Decimal:
    value = model.get(field)
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc


def _relative_change(baseline: Decimal, current: Decimal) -> Decimal:
    if baseline == 0:
        return Decimal("0") if current == 0 else Decimal("Infinity")
    return (current - baseline) / abs(baseline)


def _metric(
    *,
    name: str,
    baseline: Decimal,
    current: Decimal,
    limit: Decimal,
    relative: bool,
) -> MetricDrift:
    change = (
        _relative_change(baseline, current)
        if relative
        else current - baseline
    )
    return MetricDrift(
        metric=name,
        baseline=str(baseline),
        current=str(current),
        change=str(change),
        limit=str(limit),
        breached=change > limit,
    )


def _assert_comparable(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> None:
    fields = ("window", "horizon_business_days", "step", "quote_basis")
    baseline_benchmark = baseline.get("benchmark")
    current_benchmark = current.get("benchmark")
    if not isinstance(baseline_benchmark, dict) or not isinstance(
        current_benchmark, dict
    ):
        raise ValueError("both reports require benchmark metadata")
    changed = [
        field
        for field in fields
        if baseline_benchmark.get(field) != current_benchmark.get(field)
    ]
    if changed:
        raise ValueError(
            "reports use incompatible benchmark settings: " + ", ".join(changed)
        )


def assess_model_drift(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    model_id: str,
    policy: HedgeModelDriftPolicy = HedgeModelDriftPolicy(),
) -> HedgeModelDriftAssessment:
    """Compare like-for-like reports and fail closed on meaningful regression."""

    _assert_comparable(baseline, current)
    baseline_model = (baseline.get("models") or {}).get(model_id)
    current_model = (current.get("models") or {}).get(model_id)
    if not isinstance(baseline_model, dict):
        raise ValueError(f"{model_id}: absent from baseline report")
    if not isinstance(current_model, dict):
        raise ValueError(f"{model_id}: absent from current report")
    if baseline_model.get("scenario_centering") != current_model.get(
        "scenario_centering"
    ):
        raise ValueError("model scenario-centering policy changed")

    metrics = (
        _metric(
            name="adverse_calibration_error_increase",
            baseline=_decimal(baseline_model, "adverse_calibration_error"),
            current=_decimal(current_model, "adverse_calibration_error"),
            limit=Decimal(str(policy.maximum_calibration_error_increase)),
            relative=False,
        ),
        _metric(
            name="floor_breach_rate_increase",
            baseline=_decimal(baseline_model, "floor_breach_rate"),
            current=_decimal(current_model, "floor_breach_rate"),
            limit=Decimal(str(policy.maximum_floor_breach_increase)),
            relative=False,
        ),
        _metric(
            name="expected_shortfall_increase",
            baseline=_decimal(baseline_model, "expected_shortfall"),
            current=_decimal(current_model, "expected_shortfall"),
            limit=Decimal(str(policy.maximum_expected_shortfall_increase)),
            relative=True,
        ),
        _metric(
            name="quantile_loss_increase",
            baseline=_decimal(baseline_model, "mean_quantile_loss"),
            current=_decimal(current_model, "mean_quantile_loss"),
            limit=Decimal(str(policy.maximum_quantile_loss_increase)),
            relative=True,
        ),
        _metric(
            name="ratio_turnover_increase",
            baseline=_decimal(baseline_model, "ratio_turnover"),
            current=_decimal(current_model, "ratio_turnover"),
            limit=policy.maximum_turnover_increase,
            relative=False,
        ),
    )
    blockers = [
        f"{metric.metric} exceeded {metric.limit}"
        for metric in metrics
        if metric.breached
    ]
    tested = int(_decimal(current_model, "tested"))
    failed = int(_decimal(current_model, "failed"))
    if tested < policy.minimum_origins:
        blockers.append(
            f"tested origins {tested} < {policy.minimum_origins}"
        )
    if failed > policy.maximum_failures:
        blockers.append(
            f"model failures {failed} > {policy.maximum_failures}"
        )
    calibration = float(_decimal(current_model, "adverse_calibration_error"))
    if calibration > policy.maximum_calibration_error:
        blockers.append(
            "absolute adverse calibration error exceeds policy"
        )

    return HedgeModelDriftAssessment(
        model_id=model_id,
        status="degraded" if blockers else "healthy",
        baseline_hash=content_hash(baseline),
        current_hash=content_hash(current),
        metrics=metrics,
        blockers=tuple(blockers),
    )


MONITORING_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_drift_assessments (
    assessment_hash TEXT PRIMARY KEY,
    model_id        TEXT NOT NULL,
    baseline_hash   TEXT NOT NULL,
    current_hash    TEXT NOT NULL,
    status          TEXT NOT NULL,
    assessment      TEXT NOT NULL
);
"""


class HedgeModelMonitoringStore:
    """Append-only, content-addressed drift-assessment ledger."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(MONITORING_SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(
        self,
        assessment: HedgeModelDriftAssessment,
    ) -> dict[str, Any]:
        document = assessment.to_json()
        digest = content_hash(document)
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO model_drift_assessments"
                " (assessment_hash, model_id, baseline_hash, current_hash,"
                " status, assessment) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    digest,
                    assessment.model_id,
                    assessment.baseline_hash,
                    assessment.current_hash,
                    assessment.status,
                    canonical_json(document),
                ),
            )
        return {"assessment_hash": digest, **document}
