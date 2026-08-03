from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Mapping

from tradeflow.contracts.decision_packet import DecisionPacket
from tradeflow.contracts.evidence import EvidenceDescriptor, EvidenceRequirement
from tradeflow.contracts.interfaces import ExposureService, KnowledgeService
from tradeflow.domain.enums import DecisionStatus, EvidenceRole, Freshness
from tradeflow.domain.models import AnalysisResult, RecommendedAction, TradeProgram
from tradeflow.knowledge.evidence import validate_evidence_contract
from tradeflow.knowledge.eligibility_evidence import EligibilityFactInput
from tradeflow.knowledge.facts import FactAssembler, FactAssertion, FactBundle
from tradeflow.knowledge.mutual_account import (
    MutualAccountTimeline,
    derive_mutual_account_timeline,
)
from tradeflow.tools.exposure import DefaultExposureService


class TradeFlowPipeline:
    """Small deterministic vertical slice for the KB Comme MVP."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        exposure: ExposureService | None = None,
        fact_assembler: FactAssembler | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.exposure = exposure or DefaultExposureService()
        self.fact_assembler = fact_assembler

    def analyze(self, program: TradeProgram) -> AnalysisResult:
        exposures = self.exposure.analyze(program)
        facts = self._program_facts(program)
        snapshot_payload = [
            {
                "source_id": ref.source_id,
                "version": ref.version,
                "observed_at": ref.observed_at.isoformat(),
                "retrieved_at": ref.retrieved_at.isoformat(),
                "content_hash": ref.content_hash,
            }
            for ref in program.input_snapshots
        ]
        trade_payload: dict[str, object] = {"case_count": len(program.cases)}
        calculation_payload: dict[str, object] = {
            "engine": "tradeflow.exposure.v1"
        }
        if snapshot_payload:
            trade_payload["snapshots"] = snapshot_payload
            calculation_payload["input_snapshots"] = snapshot_payload
        generated_at = (
            max(ref.retrieved_at for ref in program.input_snapshots)
            if program.input_snapshots
            else datetime.combine(program.as_of, time.min, tzinfo=UTC)
        )

        decisions = self.knowledge.evaluate(
            topic="trade_support",
            facts=facts,
            as_of=program.as_of,
        )

        evidence: list[EvidenceDescriptor] = [
            EvidenceDescriptor(
                evidence_id=f"trade:{program.program_id}",
                role=EvidenceRole.USER_TRADE,
                identifiers=tuple(case.case_id for case in program.cases),
                source_ids=tuple(
                    dict.fromkeys(ref.source_id for ref in program.input_snapshots)
                ),
                generated_at=generated_at,
                payload=trade_payload,
            ),
            EvidenceDescriptor(
                evidence_id=f"calculation:{program.program_id}",
                role=EvidenceRole.CALCULATION,
                identifiers=tuple(exposure.currency for exposure in exposures),
                source_ids=tuple(
                    dict.fromkeys(ref.source_id for ref in program.input_snapshots)
                ),
                generated_at=generated_at,
                payload=calculation_payload,
            ),
        ]
        for decision in decisions:
            if decision.source_ids:
                evidence.append(
                    EvidenceDescriptor(
                        evidence_id=f"decision:{decision.rule_id}",
                        role=EvidenceRole.SUPPORT_ELIGIBILITY,
                        identifiers=(
                            decision.rule_id,
                            *decision.source_claim_ids,
                        ),
                        source_ids=decision.source_ids,
                        generated_at=generated_at,
                        payload={
                            "status": decision.status.value,
                            "candidate_outcome": decision.candidate_outcome,
                        },
                    )
                )

        requirements = [
            EvidenceRequirement(EvidenceRole.USER_TRADE),
            EvidenceRequirement(EvidenceRole.CALCULATION),
        ]
        if decisions:
            requirements.append(EvidenceRequirement(EvidenceRole.SUPPORT_ELIGIBILITY))
        coverage = validate_evidence_contract(requirements, evidence)

        review_reasons: list[str] = []
        if not coverage["satisfied"]:
            review_reasons.extend(f"missing evidence: {role}" for role in coverage["missing"])
        review_statuses = {
            DecisionStatus.CONDITIONALLY_ELIGIBLE,
            DecisionStatus.INSUFFICIENT_INFORMATION,
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            DecisionStatus.SOURCE_EXPIRED,
        }
        for decision in decisions:
            if decision.status in review_statuses:
                review_reasons.append(f"{decision.rule_id}: {decision.status.value}")

        return AnalysisResult(
            program_id=program.program_id,
            exposures=exposures,
            decisions=decisions,
            evidence=tuple(evidence),
            evidence_coverage=coverage,
            review_required=bool(review_reasons),
            review_reasons=tuple(dict.fromkeys(review_reasons)),
            actions=self._project_actions(decisions, {}),
        )

    def analyze_packet(self, program: TradeProgram) -> DecisionPacket:
        """Run deterministic analysis and seal its output for synthesis."""
        return DecisionPacket.from_analysis(
            self.analyze(program),
            as_of=program.as_of,
            inputs=self._program_facts(program),
        )

    def analyze_cases(
        self,
        program: TradeProgram,
        *,
        assertions_by_case: Mapping[str, tuple[FactAssertion, ...]],
        evidence: tuple[EvidenceDescriptor, ...],
        source_freshness: Mapping[str, Freshness] | None = None,
        mutual_account_timelines: Mapping[str, MutualAccountTimeline] | None = None,
    ) -> AnalysisResult:
        """Run the real case-level support and FX-compliance rule topics."""
        result, _ = self._analyze_cases(
            program,
            assertions_by_case=assertions_by_case,
            evidence=evidence,
            source_freshness=source_freshness,
            mutual_account_timelines=mutual_account_timelines,
        )
        return result

    def analyze_cases_with_eligibility(
        self,
        program: TradeProgram,
        *,
        eligibility: EligibilityFactInput,
        assertions_by_case: Mapping[str, tuple[FactAssertion, ...]] | None = None,
        evidence: tuple[EvidenceDescriptor, ...] = (),
        source_freshness: Mapping[str, Freshness] | None = None,
        mutual_account_timelines: Mapping[str, MutualAccountTimeline] | None = None,
    ) -> AnalysisResult:
        """Run case rules with provider-built eligibility evidence.

        Stale provider records remain in the audit evidence but cannot attest a
        fact and are ignored by evidence coverage.
        """
        result, _ = self._analyze_cases(
            program,
            assertions_by_case=self._merge_eligibility_assertions(
                eligibility,
                assertions_by_case or {},
            ),
            evidence=(
                *evidence,
                *eligibility.evidence,
                *eligibility.unusable_evidence,
            ),
            source_freshness=source_freshness,
            mutual_account_timelines=mutual_account_timelines,
        )
        return self._apply_eligibility_review(result, eligibility)

    def analyze_case_packet(
        self,
        program: TradeProgram,
        *,
        assertions_by_case: Mapping[str, tuple[FactAssertion, ...]],
        evidence: tuple[EvidenceDescriptor, ...],
        source_freshness: Mapping[str, Freshness] | None = None,
        mutual_account_timelines: Mapping[str, MutualAccountTimeline] | None = None,
    ) -> DecisionPacket:
        result, bundles = self._analyze_cases(
            program,
            assertions_by_case=assertions_by_case,
            evidence=evidence,
            source_freshness=source_freshness,
            mutual_account_timelines=mutual_account_timelines,
        )
        inputs = {
            "program": self._program_facts(program),
            "cases": {
                bundle.case_id: dict(bundle.facts)
                for bundle in bundles
            },
        }
        return DecisionPacket.from_analysis(
            result,
            as_of=program.as_of,
            inputs=inputs,
        )

    def analyze_case_packet_with_eligibility(
        self,
        program: TradeProgram,
        *,
        eligibility: EligibilityFactInput,
        assertions_by_case: Mapping[str, tuple[FactAssertion, ...]] | None = None,
        evidence: tuple[EvidenceDescriptor, ...] = (),
        source_freshness: Mapping[str, Freshness] | None = None,
        mutual_account_timelines: Mapping[str, MutualAccountTimeline] | None = None,
    ) -> DecisionPacket:
        merged_assertions = self._merge_eligibility_assertions(
            eligibility,
            assertions_by_case or {},
        )
        result, bundles = self._analyze_cases(
            program,
            assertions_by_case=merged_assertions,
            evidence=(
                *evidence,
                *eligibility.evidence,
                *eligibility.unusable_evidence,
            ),
            source_freshness=source_freshness,
            mutual_account_timelines=mutual_account_timelines,
        )
        result = self._apply_eligibility_review(result, eligibility)
        return DecisionPacket.from_analysis(
            result,
            as_of=program.as_of,
            inputs={
                "program": self._program_facts(program),
                "cases": {
                    bundle.case_id: dict(bundle.facts)
                    for bundle in bundles
                },
                "eligibility_evidence": {
                    "stale_evidence_ids": list(eligibility.stale_evidence_ids),
                    "missing_fields_by_case": {
                        case_id: list(fields)
                        for case_id, fields in eligibility.missing_fields_by_case.items()
                    },
                },
            },
        )

    @staticmethod
    def _merge_eligibility_assertions(
        eligibility: EligibilityFactInput,
        additional: Mapping[str, tuple[FactAssertion, ...]],
    ) -> dict[str, tuple[FactAssertion, ...]]:
        case_ids = set(eligibility.assertions_by_case) | set(additional)
        return {
            case_id: (
                *eligibility.assertions_by_case.get(case_id, ()),
                *additional.get(case_id, ()),
            )
            for case_id in case_ids
        }

    @staticmethod
    def _apply_eligibility_review(
        result: AnalysisResult,
        eligibility: EligibilityFactInput,
    ) -> AnalysisResult:
        reasons = list(result.review_reasons)
        has_missing = False
        for case_id, fields in eligibility.missing_fields_by_case.items():
            if not fields:
                continue
            has_missing = True
            reasons.append(
                f"{case_id}: missing eligibility evidence: {', '.join(fields)}"
            )
        if has_missing and eligibility.stale_evidence_ids:
            reasons.append(
                "stale eligibility evidence: "
                + ", ".join(eligibility.stale_evidence_ids)
            )
        deduplicated = tuple(dict.fromkeys(reasons))
        if deduplicated == result.review_reasons:
            return result
        return replace(
            result,
            review_required=bool(deduplicated),
            review_reasons=deduplicated,
        )

    def _analyze_cases(
        self,
        program: TradeProgram,
        *,
        assertions_by_case: Mapping[str, tuple[FactAssertion, ...]],
        evidence: tuple[EvidenceDescriptor, ...],
        source_freshness: Mapping[str, Freshness] | None,
        mutual_account_timelines: Mapping[str, MutualAccountTimeline] | None,
    ) -> tuple[AnalysisResult, tuple[FactBundle, ...]]:
        if self.fact_assembler is None:
            raise ValueError("case analysis requires a FactAssembler")
        known_case_ids = {case.case_id for case in program.cases}
        unknown_case_ids = set(assertions_by_case) - known_case_ids
        timeline_by_case = mutual_account_timelines or {}
        unknown_case_ids.update(set(timeline_by_case) - known_case_ids)
        if unknown_case_ids:
            raise ValueError(
                "case inputs reference unknown cases: "
                + ", ".join(sorted(unknown_case_ids))
            )

        exposures = self.exposure.analyze(program)
        base_evidence = self._base_evidence(program, exposures)
        derived_by_case = {
            case_id: derive_mutual_account_timeline(
                case_id=case_id,
                timeline=timeline,
                as_of=program.as_of,
            )
            for case_id, timeline in timeline_by_case.items()
        }
        derived_evidence = tuple(
            item.evidence for item in derived_by_case.values()
        )
        all_evidence = (*base_evidence, *evidence, *derived_evidence)
        evidence_ids = [item.evidence_id for item in all_evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence contains duplicate evidence_id values")

        bundles: list[FactBundle] = []
        decisions = []
        decision_evidence: list[EvidenceDescriptor] = []
        for case in program.cases:
            bundle = self.fact_assembler.assemble(
                program=program,
                case=case,
                assertions=(
                    *assertions_by_case.get(case.case_id, ()),
                    *(
                        derived_by_case[case.case_id].assertions
                        if case.case_id in derived_by_case
                        else ()
                    ),
                ),
                evidence=all_evidence,
            )
            bundles.append(bundle)
            for topic, role in (
                ("trade_support_case", EvidenceRole.SUPPORT_ELIGIBILITY),
                ("fx_compliance", EvidenceRole.COMPLIANCE),
            ):
                case_decisions = self.knowledge.evaluate(
                    topic=topic,
                    facts=dict(bundle.facts),
                    as_of=program.as_of,
                    source_freshness=source_freshness,
                    subject_id=case.case_id,
                )
                decisions.extend(case_decisions)
                for decision in case_decisions:
                    if decision.source_ids:
                        decision_evidence.append(
                            EvidenceDescriptor(
                                evidence_id=(
                                    f"decision:{case.case_id}:{decision.rule_id}"
                                ),
                                role=role,
                                identifiers=(
                                    case.case_id,
                                    decision.rule_id,
                                    *decision.source_claim_ids,
                                ),
                                source_ids=decision.source_ids,
                                generated_at=base_evidence[0].generated_at,
                                payload={
                                    "status": decision.status.value,
                                    "candidate_outcome": decision.candidate_outcome,
                                },
                            )
                        )

        complete_evidence = (*all_evidence, *decision_evidence)
        requirements = [
            EvidenceRequirement(EvidenceRole.USER_TRADE),
            EvidenceRequirement(EvidenceRole.CALCULATION),
        ]
        if any(item.role is EvidenceRole.SUPPORT_ELIGIBILITY for item in decision_evidence):
            requirements.append(EvidenceRequirement(EvidenceRole.SUPPORT_ELIGIBILITY))
        if any(item.role is EvidenceRole.COMPLIANCE for item in decision_evidence):
            requirements.append(EvidenceRequirement(EvidenceRole.COMPLIANCE))
        coverage = validate_evidence_contract(requirements, complete_evidence)
        review_reasons = self._review_reasons(tuple(decisions), coverage)
        if any(
            item.role is EvidenceRole.USER_DECLARATION
            for item in all_evidence
        ):
            review_reasons = tuple(
                dict.fromkeys(
                    (
                        *review_reasons,
                        "기업 자기선언 사실은 공식 자격 증거로 확인해야 합니다",
                    )
                )
            )
        deadlines_by_case = {
            case_id: item.deadlines
            for case_id, item in derived_by_case.items()
        }
        actions = self._project_actions(tuple(decisions), deadlines_by_case)
        return (
            AnalysisResult(
                program_id=program.program_id,
                exposures=exposures,
                decisions=tuple(decisions),
                evidence=complete_evidence,
                evidence_coverage=coverage,
                review_required=bool(review_reasons),
                review_reasons=review_reasons,
                actions=actions,
            ),
            tuple(bundles),
        )

    def _project_actions(
        self,
        decisions,
        deadlines_by_case: Mapping[str, Mapping[str, date]],
    ) -> tuple[RecommendedAction, ...]:
        actions: list[RecommendedAction] = []
        for decision in decisions:
            if decision.matched is not True:
                continue
            procedure = self.knowledge.procedure_for(decision.rule_id)
            if not procedure:
                continue
            outcome = procedure["candidate_outcome"]
            action_name = outcome.get("action")
            if not isinstance(action_name, str) or not action_name:
                continue
            deadline = None
            deadline_key = outcome.get("deadline_key")
            if deadline_key and decision.subject_id:
                deadline = deadlines_by_case.get(decision.subject_id, {}).get(
                    deadline_key
                )
            actions.append(
                RecommendedAction(
                    subject_id=decision.subject_id,
                    rule_ids=(decision.rule_id,),
                    product_ids=(
                        (outcome["product_id"],)
                        if isinstance(outcome.get("product_id"), str)
                        else ()
                    ),
                    authority=outcome.get("authority"),
                    action=action_name,
                    timing=outcome.get("timing"),
                    deadline=deadline,
                    requirements=decision.requirements,
                    required_documents=tuple(procedure["required_documents"]),
                    steps=tuple(procedure["steps"]),
                    source_ids=tuple(procedure["source_ids"]),
                    source_claim_ids=tuple(procedure["source_claim_ids"]),
                    document_set_ids=tuple(procedure["document_set_ids"]),
                    document_requirements=tuple(
                        procedure["document_requirements"]
                    ),
                )
            )
        return self._merge_actions(actions)

    @staticmethod
    def _merge_actions(
        actions: list[RecommendedAction],
    ) -> tuple[RecommendedAction, ...]:
        merged: list[RecommendedAction] = []
        for action in actions:
            key = (
                action.subject_id,
                action.authority,
                action.action,
                action.timing,
                action.deadline,
                action.product_ids,
            )
            existing_index = next(
                (
                    index
                    for index, item in enumerate(merged)
                    if (
                        item.subject_id,
                        item.authority,
                        item.action,
                        item.timing,
                        item.deadline,
                        item.product_ids,
                    )
                    == key
                ),
                None,
            )
            if existing_index is None:
                merged.append(action)
                continue
            existing = merged[existing_index]
            merged[existing_index] = RecommendedAction(
                subject_id=existing.subject_id,
                rule_ids=tuple(
                    dict.fromkeys((*existing.rule_ids, *action.rule_ids))
                ),
                product_ids=tuple(
                    dict.fromkeys((*existing.product_ids, *action.product_ids))
                ),
                authority=existing.authority,
                action=existing.action,
                timing=existing.timing,
                deadline=existing.deadline,
                requirements=_unique_items(
                    (*existing.requirements, *action.requirements)
                ),
                required_documents=tuple(
                    dict.fromkeys(
                        (
                            *existing.required_documents,
                            *action.required_documents,
                        )
                    )
                ),
                steps=tuple(
                    dict.fromkeys((*existing.steps, *action.steps))
                ),
                source_ids=tuple(
                    dict.fromkeys((*existing.source_ids, *action.source_ids))
                ),
                source_claim_ids=tuple(
                    dict.fromkeys(
                        (*existing.source_claim_ids, *action.source_claim_ids)
                    )
                ),
                document_set_ids=tuple(
                    dict.fromkeys(
                        (*existing.document_set_ids, *action.document_set_ids)
                    )
                ),
                document_requirements=_merge_document_requirements(
                    existing.document_requirements,
                    action.document_requirements,
                ),
            )
        return tuple(merged)

    def _base_evidence(self, program: TradeProgram, exposures) -> tuple[EvidenceDescriptor, ...]:
        snapshot_payload = [
            {
                "source_id": ref.source_id,
                "version": ref.version,
                "observed_at": ref.observed_at.isoformat(),
                "retrieved_at": ref.retrieved_at.isoformat(),
                "content_hash": ref.content_hash,
            }
            for ref in program.input_snapshots
        ]
        generated_at = (
            max(ref.retrieved_at for ref in program.input_snapshots)
            if program.input_snapshots
            else datetime.combine(program.as_of, time.min, tzinfo=UTC)
        )
        trade_payload: dict[str, object] = {"case_count": len(program.cases)}
        calculation_payload: dict[str, object] = {
            "engine": "tradeflow.exposure.v1"
        }
        if snapshot_payload:
            trade_payload["snapshots"] = snapshot_payload
            calculation_payload["input_snapshots"] = snapshot_payload
        source_ids = tuple(
            dict.fromkeys(ref.source_id for ref in program.input_snapshots)
        )
        return (
            EvidenceDescriptor(
                evidence_id=f"trade:{program.program_id}",
                role=EvidenceRole.USER_TRADE,
                identifiers=tuple(case.case_id for case in program.cases),
                source_ids=source_ids,
                generated_at=generated_at,
                payload=trade_payload,
            ),
            EvidenceDescriptor(
                evidence_id=f"calculation:{program.program_id}",
                role=EvidenceRole.CALCULATION,
                identifiers=tuple(exposure.currency for exposure in exposures),
                source_ids=source_ids,
                generated_at=generated_at,
                payload=calculation_payload,
            ),
        )

    @staticmethod
    def _review_reasons(decisions, coverage) -> tuple[str, ...]:
        reasons: list[str] = []
        if not coverage["satisfied"]:
            reasons.extend(
                f"missing evidence: {role}" for role in coverage["missing"]
            )
        review_statuses = {
            DecisionStatus.CONDITIONALLY_ELIGIBLE,
            DecisionStatus.INSUFFICIENT_INFORMATION,
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            DecisionStatus.SOURCE_EXPIRED,
        }
        for decision in decisions:
            if decision.status in review_statuses:
                subject = f"{decision.subject_id}:" if decision.subject_id else ""
                reasons.append(
                    f"{subject}{decision.rule_id}: {decision.status.value}"
                )
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _program_facts(program: TradeProgram) -> dict[str, object]:
        facts = program.company.facts()
        directions = {case.direction.value for case in program.cases}
        facts["program.has_export"] = "export" in directions
        facts["program.has_import"] = "import" in directions
        facts["program.currencies"] = sorted({case.currency for case in program.cases})
        if program.input_snapshots:
            facts["program.input_snapshots"] = [
                {
                    "source_id": ref.source_id,
                    "version": ref.version,
                    "observed_at": ref.observed_at.isoformat(),
                    "content_hash": ref.content_hash,
                }
                for ref in program.input_snapshots
            ]
        return facts


def _unique_items(items):
    unique = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return tuple(unique)


def _merge_document_requirements(*groups):
    merged = {}
    for group in groups:
        for requirement in group:
            existing = merged.get(requirement.requirement_id)
            if existing is not None and existing != requirement:
                raise ValueError(
                    "conflicting document requirement: "
                    f"{requirement.requirement_id}"
                )
            merged[requirement.requirement_id] = requirement
    return tuple(merged.values())
