"""Deterministic user-profile classification and capability routing.

The module does not decide product eligibility or synthesize bank endpoints.
It converts normalized profile facts into presentation segments and abstract
capability requests whose provider bindings live at the integration edge.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from tradeflow.contracts.profile_policy import (
    CapabilityRequest,
    FactProvenance,
    PolicyRoute,
    ProfileFact,
    ProfilePolicyResult,
    SegmentClassification,
    SegmentMatch,
    UserProfileFacts,
)


SME_SIZES = {"micro", "small", "medium"}
MATERIALS_DEFENSE_TAGS = {
    "materials",
    "components",
    "equipment",
    "defense",
}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return {str(item) for item in value}
    return set()


def _append_unique(items: list[str], *values: str) -> None:
    for value in values:
        if value and value not in items:
            items.append(value)


def _fact_index(
    profile: UserProfileFacts,
) -> dict[str, tuple[ProfileFact, ...]]:
    grouped: dict[str, list[ProfileFact]] = defaultdict(list)
    for fact in profile.facts:
        grouped[fact.field].append(fact)
    return {key: tuple(value) for key, value in grouped.items()}


def _fact_evidence_ids(
    facts: Iterable[ProfileFact],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(item.evidence_id for item in facts if item.evidence_id)
    )


def _profile_fact_state(
    facts_by_field: Mapping[str, tuple[ProfileFact, ...]],
) -> tuple[str, bool]:
    conflicting = False
    for facts in facts_by_field.values():
        usable = [
            item
            for item in facts
            if item.provenance
            in {FactProvenance.VERIFIED, FactProvenance.USER_DECLARED}
        ]
        values = {str(item.value) for item in usable}
        if len(values) > 1 or any(
            item.provenance is FactProvenance.CONFLICTING for item in facts
        ):
            conflicting = True
            break
    if conflicting:
        return "conflicting", True
    if any(
        fact.provenance is FactProvenance.STALE
        for facts in facts_by_field.values()
        for fact in facts
    ):
        return "stale", True
    return "available", False


def _export_volume(
    profile: UserProfileFacts,
    facts_by_field: Mapping[str, tuple[ProfileFact, ...]],
    missing_fields: list[str],
) -> tuple[Decimal | None, tuple[str, ...], str | None]:
    field = "trade.export_volume.trailing_12m_usd"
    facts = facts_by_field.get(field, ())
    usable_values = {
        str(item.value)
        for item in facts
        if item.provenance
        in {FactProvenance.VERIFIED, FactProvenance.USER_DECLARED}
    }
    if len(usable_values) > 1:
        return None, _fact_evidence_ids(facts), FactProvenance.CONFLICTING.value
    if facts:
        preferred = next(
            (
                item
                for item in facts
                if item.provenance is FactProvenance.VERIFIED
            ),
            facts[0],
        )
        return (
            _decimal(preferred.value),
            _fact_evidence_ids((preferred,)),
            preferred.provenance.value,
        )

    ranged = profile.values.get("export_volume")
    if isinstance(ranged, Mapping) and ranged.get("kind") == "range":
        if ranged.get("lower_usd") is None:
            _append_unique(missing_fields, "trade.export_volume.lower_usd")
            return None, (), None
        return _decimal(ranged.get("lower_usd")), (), FactProvenance.ESTIMATED.value

    direct = profile.values.get("export_volume_trailing_12m_usd")
    if direct is None:
        direct = profile.values.get("user_declared_export_volume_usd")
    provenance = FactProvenance.USER_DECLARED.value if direct is not None else None
    return _decimal(direct), (), provenance


def classify_profile(profile: UserProfileFacts) -> SegmentClassification:
    values = profile.values
    facts_by_field = _fact_index(profile)
    missing_fields: list[str] = []
    fact_status, review_required = _profile_fact_state(facts_by_field)
    export_volume, export_evidence, used_provenance = _export_volume(
        profile,
        facts_by_field,
        missing_fields,
    )
    if (
        values.get("trade_history_status") == FactProvenance.UNAVAILABLE.value
        and values.get("user_declared_export_volume_usd") is not None
    ):
        _append_unique(
            missing_fields,
            "verified.trade.export_volume.trailing_12m_usd",
        )

    company_size = str(values.get("company_size") or "")
    trade_roles = _string_set(values.get("trade_roles"))
    financing_needs = _string_set(values.get("financing_needs"))
    industry_tags = _string_set(values.get("industry_tags"))
    maturity = values.get("trade_maturity_months")
    maturity_months = int(maturity) if isinstance(maturity, int) else None

    axes: dict[str, list[str]] = {
        "company_stage": [],
        "trade_role": [],
        "relationship": [],
        "risk": [],
    }
    verified_exporter = (
        used_provenance == FactProvenance.VERIFIED.value
        and export_volume is not None
        and export_volume > 0
    )
    effective_trade_roles = set(trade_roles)
    if verified_exporter:
        effective_trade_roles.add("exporter")
    for role in ("exporter", "importer", "potential_exporter"):
        if role in effective_trade_roles:
            axes["trade_role"].append(role)
    if maturity_months is not None:
        axes["company_stage"].append(
            "early_trade" if maturity_months < 12 else "established_trade"
        )

    matches: list[SegmentMatch] = []
    primary_candidates: list[str] = []
    secondary: list[str] = []

    export_conflict = fact_status == "conflicting" and bool(
        facts_by_field.get("trade.export_volume.trailing_12m_usd")
    )
    established = (
        company_size in SME_SIZES
        and "exporter" in effective_trade_roles
        and maturity_months is not None
        and maturity_months >= 12
        and export_volume is not None
        and export_volume > 0
        and not export_conflict
    )
    if established:
        primary_candidates.append("existing_exporter_sme")
        matches.append(
            SegmentMatch(
                type="existing_exporter_sme",
                score="1.0",
                evidence_ids=export_evidence,
                matched_facts=(
                    "중소·중견 규모",
                    "최근 12개월 수출실적 양수",
                    "무역 경력 12개월 이상",
                ),
            )
        )

    potential = "potential_exporter" in trade_roles and (
        export_volume == 0 or values.get("has_export_contract") is True
    )
    if potential and not export_conflict:
        primary_candidates.append("potential_exporter")
        matches.append(
            SegmentMatch(
                type="potential_exporter",
                score="1.0",
                evidence_ids=export_evidence,
                matched_facts=("잠재수출 역할", "수출계약 또는 무실적",),
            )
        )

    startup = values.get("startup") is True or (
        isinstance(values.get("established_year"), int)
        and values.get("as_of_year")
        and int(values["as_of_year"]) - int(values["established_year"]) <= 5
    )
    if startup and maturity_months is not None and maturity_months < 12:
        primary_candidates.append("startup_early_exporter")
        matches.append(
            SegmentMatch(
                type="startup_early_exporter",
                score="1.0",
                matched_facts=("창업 초기", "무역 경력 12개월 미만"),
            )
        )

    if "importer" in trade_roles and "import_usance" in financing_needs:
        if industry_tags & MATERIALS_DEFENSE_TAGS:
            primary_candidates.append("materials_defense_importer")
            matches.append(
                SegmentMatch(
                    type="materials_defense_importer",
                    score="1.0",
                    matched_facts=("수입기업", "유산스 수요", "소부장·방산 업종"),
                )
            )
        elif not industry_tags:
            _append_unique(missing_fields, "company.industry_tags")

    relationships = values.get("supplier_relationships") or []
    verified_relationships = [
        item
        for item in relationships
        if isinstance(item, Mapping)
        and item.get("provenance") == FactProvenance.VERIFIED.value
        and item.get("evidence_id")
    ]
    if verified_relationships:
        axes["relationship"].append("supplier_tier_1")
        secondary.append("supply_chain_supplier")
        matches.append(
            SegmentMatch(
                type="supply_chain_supplier",
                score="1.0",
                evidence_ids=tuple(
                    dict.fromkeys(
                        str(item["evidence_id"])
                        for item in verified_relationships
                    )
                ),
                matched_facts=("검증된 협력사 관계",),
            )
        )

    cashflows = values.get("currency_cashflows") or []
    open_exposure = any(
        _decimal(item.get("net_amount")) not in {None, Decimal("0")}
        for item in cashflows
        if isinstance(item, Mapping)
    )
    hedge_ratio = _decimal(values.get("existing_hedge_ratio"))
    if open_exposure and hedge_ratio is not None and hedge_ratio < Decimal("0.5"):
        axes["risk"].append("fx_sensitive")
        secondary.append("fx_sensitive")
        matches.append(
            SegmentMatch(
                type="fx_sensitive",
                score="0.84",
                matched_facts=("외화 순노출 존재", "기존 헤지 비율 50% 미만"),
                missing_fields=("risk.loss_tolerance",)
                if values.get("loss_tolerance") is None
                else (),
            )
        )

    country_policy = values.get("country_policy")
    if isinstance(country_policy, Mapping):
        policy_provenance = country_policy.get("provenance")
        if (
            policy_provenance == FactProvenance.VERIFIED.value
            and country_policy.get("status") == "restricted"
        ):
            axes["risk"].append("high_risk_country")
            secondary.append("high_risk_country_trade")
            evidence_id = country_policy.get("evidence_id")
            matches.append(
                SegmentMatch(
                    type="high_risk_country_trade",
                    score="1.0",
                    evidence_ids=(str(evidence_id),) if evidence_id else (),
                    matched_facts=("검증된 현행 국가정책상 제한",),
                )
            )
        elif policy_provenance == FactProvenance.STALE.value:
            review_required = True

    primary_type = primary_candidates[0] if primary_candidates else None
    for candidate in primary_candidates[1:]:
        _append_unique(secondary, candidate)

    return SegmentClassification(
        axes={key: tuple(item) for key, item in axes.items()},
        primary_type=primary_type,
        secondary_types=tuple(dict.fromkeys(secondary)),
        classifications=tuple(matches),
        missing_fields=tuple(missing_fields),
        fact_status=fact_status,
        used_provenance=used_provenance,
        review_required=review_required,
    )


def route_profile_policy(
    profile: UserProfileFacts,
    classification: SegmentClassification,
) -> PolicyRoute:
    values = profile.values
    primary_type = values.get("primary_type") or classification.primary_type
    secondary_types = set(classification.secondary_types)
    consents = _string_set(values.get("consents"))
    capabilities: list[CapabilityRequest] = []
    executed: list[str] = []
    missing_consents: list[str] = []
    fallback: str | None = None
    priority_views: list[str] = []

    if primary_type == "existing_exporter_sme":
        priority_views.extend(["trade_history", "funding_gap", "fx_risk"])
        consent = "company_trade_data.read"
        executable = consent in consents
        capabilities.append(
            CapabilityRequest(
                capability_id="trade_history.lookup.v1",
                reason="최근 수출실적 확인",
                required_consent=consent,
                required_inputs=("company_id", "period"),
                fallback="manual_evidence_request",
                executable=executable,
            )
        )
        if executable:
            executed.append("trade_history.lookup.v1")
        else:
            missing_consents.append(consent)
            fallback = "manual_evidence_request"

    country_policy = values.get("country_policy")
    if isinstance(country_policy, Mapping) and (
        country_policy.get("provenance") == FactProvenance.STALE.value
    ):
        capabilities.append(
            CapabilityRequest(
                capability_id="country_policy.refresh.v1",
                reason="만료된 국가정책 갱신",
                required_inputs=("country", "as_of"),
                fallback="expert_review",
                executable=False,
            )
        )
        fallback = fallback or "expert_review"

    if "fx_sensitive" in secondary_types:
        _append_unique(priority_views, "fx_risk", "hedge_scenarios")

    decision_status: str | None = None
    allowed_outputs: tuple[str, ...] = ()
    if (
        primary_type == "potential_exporter"
        and values.get("eligibility_evidence") == []
    ):
        decision_status = "missing_information"
        allowed_outputs = (
            "product_discovery_candidate",
            "required_information",
        )

    handoff_mode: str | None = None
    transmission_performed = False
    if (
        values.get("bank_provider_status") == "unavailable"
        and values.get("consultation_consent") is True
    ):
        handoff_mode = "manual_packet"

    return PolicyRoute(
        priority_views=tuple(dict.fromkeys(priority_views)),
        capabilities=tuple(capabilities),
        executed_capabilities=tuple(executed),
        missing_consents=tuple(missing_consents),
        fallback=fallback,
        decision_status=decision_status,
        allowed_outputs=allowed_outputs,
        handoff_mode=handoff_mode,
        transmission_performed=transmission_performed,
    )


def evaluate_profile_policy(
    payload: Mapping[str, Any] | UserProfileFacts,
) -> ProfilePolicyResult:
    profile = (
        payload
        if isinstance(payload, UserProfileFacts)
        else UserProfileFacts.from_mapping(payload)
    )
    classification = classify_profile(profile)
    route = route_profile_policy(profile, classification)
    return ProfilePolicyResult(
        profile=profile,
        classification=classification,
        route=route,
    )
