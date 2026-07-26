from tradeflow.contracts.evidence import EvidenceDescriptor, EvidenceRequirement
from tradeflow.contracts.interfaces import ExposureService, KnowledgeService
from tradeflow.domain.enums import DecisionStatus, EvidenceRole
from tradeflow.domain.models import AnalysisResult, TradeProgram
from tradeflow.knowledge.evidence import validate_evidence_contract
from tradeflow.tools.exposure import DefaultExposureService


class TradeFlowPipeline:
    """Small deterministic vertical slice for the TradeFlow MVP."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        exposure: ExposureService | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.exposure = exposure or DefaultExposureService()

    def analyze(self, program: TradeProgram) -> AnalysisResult:
        exposures = self.exposure.analyze(program)
        facts = program.company.facts()
        directions = {case.direction.value for case in program.cases}
        facts["program.has_export"] = "export" in directions
        facts["program.has_import"] = "import" in directions
        facts["program.currencies"] = sorted({case.currency for case in program.cases})

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
                payload={"case_count": len(program.cases)},
            ),
            EvidenceDescriptor(
                evidence_id=f"calculation:{program.program_id}",
                role=EvidenceRole.CALCULATION,
                identifiers=tuple(exposure.currency for exposure in exposures),
                payload={"engine": "tradeflow.exposure.v1"},
            ),
        ]
        for decision in decisions:
            if decision.source_ids:
                evidence.append(
                    EvidenceDescriptor(
                        evidence_id=f"decision:{decision.rule_id}",
                        role=EvidenceRole.SUPPORT_ELIGIBILITY,
                        identifiers=(decision.rule_id,),
                        source_ids=decision.source_ids,
                        payload={"status": decision.status.value},
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
        )
