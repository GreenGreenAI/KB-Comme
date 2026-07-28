"""Declarative governance contract for champion and challenger hedge models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


MODEL_STATUSES = frozenset({"champion", "challenger", "data_blocked"})


@dataclass(frozen=True)
class GovernedHedgeModel:
    model_id: str
    version: str
    status: str
    family: str
    scenario_centering: str
    objective: str
    implementation: str
    references: tuple[str, ...]
    parameters: Mapping[str, Any]
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )


@dataclass(frozen=True)
class HedgeModelGovernanceRegistry:
    schema_version: str
    champion_model_id: str
    models: Mapping[str, GovernedHedgeModel]
    promotion_policy: Mapping[str, Any]
    fallback_policy: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", MappingProxyType(dict(self.models)))
        object.__setattr__(
            self,
            "promotion_policy",
            MappingProxyType(dict(self.promotion_policy)),
        )
        object.__setattr__(
            self,
            "fallback_policy",
            MappingProxyType(dict(self.fallback_policy)),
        )

    @classmethod
    def from_json(cls, path: Path | str) -> "HedgeModelGovernanceRegistry":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != "1.0":
            raise ValueError("unsupported hedge model registry schema")
        models: dict[str, GovernedHedgeModel] = {}
        for item in document.get("models", []):
            model = GovernedHedgeModel(
                model_id=_required(item, "model_id"),
                version=_required(item, "version"),
                status=_required(item, "status"),
                family=_required(item, "family"),
                scenario_centering=_required(item, "scenario_centering"),
                objective=_required(item, "objective"),
                implementation=_required(item, "implementation"),
                references=tuple(item.get("references", [])),
                parameters=dict(item.get("parameters", {})),
                blockers=tuple(item.get("blockers", [])),
            )
            if model.model_id in models:
                raise ValueError(f"duplicate governed model_id: {model.model_id}")
            if model.status not in MODEL_STATUSES:
                raise ValueError(f"unknown hedge model status: {model.status}")
            if not model.references:
                raise ValueError(f"{model.model_id}: references are required")
            if any(
                not reference.startswith("https://")
                for reference in model.references
            ):
                raise ValueError(
                    f"{model.model_id}: references must use HTTPS"
                )
            if model.status == "data_blocked" and not model.blockers:
                raise ValueError(
                    f"{model.model_id}: data-blocked model needs blockers"
                )
            models[model.model_id] = model

        champion_id = _required(document, "champion_model_id")
        champions = [
            model.model_id
            for model in models.values()
            if model.status == "champion"
        ]
        if champions != [champion_id]:
            raise ValueError(
                "registry must contain exactly the declared champion"
            )
        promotion = document.get("promotion_policy")
        fallback = document.get("fallback_policy")
        if not isinstance(promotion, dict) or not isinstance(fallback, dict):
            raise ValueError("promotion and fallback policies are required")
        required_roles = promotion.get("required_approvals")
        if (
            not isinstance(required_roles, list)
            or len(required_roles) != 3
            or len(set(required_roles)) != 3
        ):
            raise ValueError("three unique model approval roles are required")
        allowed_centering = promotion.get("allowed_scenario_centering")
        if (
            not isinstance(allowed_centering, list)
            or not allowed_centering
            or len(set(allowed_centering)) != len(allowed_centering)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in allowed_centering
            )
        ):
            raise ValueError(
                "allowed scenario centering values must be unique "
                "non-empty strings"
            )
        if models[champion_id].scenario_centering not in allowed_centering:
            raise ValueError(
                "champion scenario centering must be allowed by promotion policy"
            )
        if fallback.get("automatic_challenger_fallback") is not False:
            raise ValueError("automatic challenger fallback is forbidden")
        return cls(
            schema_version="1.0",
            champion_model_id=champion_id,
            models=models,
            promotion_policy=promotion,
            fallback_policy=fallback,
        )


def _required(document: Mapping[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()
