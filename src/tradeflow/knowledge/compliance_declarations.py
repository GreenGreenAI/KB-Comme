"""Case-scoped user declarations for compliance gateway facts.

A declaration may answer only whether a regulated payment pattern is present.
It cannot attest a legal exception, a filing status, or a derived deadline.
Those facts remain bound to their dedicated compliance, procedure, or
calculation evidence paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import EvidenceRole
from tradeflow.domain.models import TradeProgram
from tradeflow.domain.snapshot import require_aware
from tradeflow.knowledge.facts import (
    FactAssertion,
    FactCatalog,
    FactContractError,
)


USER_DECLARATION_SOURCE_ID = "USER_DECLARATION"
DECLARATION_KIND = "company_compliance_scope_gate"
DECLARABLE_GATEWAY_FIELDS = (
    "payment.is_netting",
    "payment.is_third_party",
    "payment.uses_mutual_account",
    "payment.uses_foreign_exchange_bank",
)


@dataclass(frozen=True)
class ComplianceGatewayDeclaration:
    """A company's confirmed description of one case's payment structure."""

    declaration_id: str
    company_id: str
    case_id: str
    declared_at: datetime
    declared_by_role: str
    confirmed: bool
    is_netting: bool | None = None
    is_third_party: bool | None = None
    uses_mutual_account: bool | None = None
    uses_foreign_exchange_bank: bool | None = None

    def __post_init__(self) -> None:
        for name in ("declaration_id", "company_id", "case_id", "declared_by_role"):
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        require_aware(self.declared_at, "declared_at")
        if self.confirmed is not True:
            raise ValueError("compliance gateway declaration must be confirmed")
        values = (
            self.is_netting,
            self.is_third_party,
            self.uses_mutual_account,
            self.uses_foreign_exchange_bank,
        )
        if all(value is None for value in values):
            raise ValueError("declaration must contain at least one gateway fact")
        if any(value is not None and not isinstance(value, bool) for value in values):
            raise TypeError("gateway fact values must be boolean or None")

    def facts(self) -> Mapping[str, bool]:
        values = (
            ("payment.is_netting", self.is_netting),
            ("payment.is_third_party", self.is_third_party),
            ("payment.uses_mutual_account", self.uses_mutual_account),
            (
                "payment.uses_foreign_exchange_bank",
                self.uses_foreign_exchange_bank,
            ),
        )
        return MappingProxyType(
            {field: value for field, value in values if value is not None}
        )


@dataclass(frozen=True)
class ComplianceDeclarationInput:
    """Fact and evidence inputs accepted by the deterministic case pipeline."""

    assertions_by_case: Mapping[str, tuple[FactAssertion, ...]]
    evidence: tuple[EvidenceDescriptor, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assertions_by_case",
            MappingProxyType(dict(self.assertions_by_case)),
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))


class ComplianceDeclarationAssembler:
    """Validate declarations and turn them into evidence-bound facts."""

    def __init__(self, catalog: FactCatalog) -> None:
        self.catalog = catalog
        for field in DECLARABLE_GATEWAY_FIELDS:
            definition = catalog.definitions.get(field)
            if definition is None:
                raise FactContractError(f"declarable gateway fact is missing: {field}")
            if definition.evidence_role is not EvidenceRole.COMPLIANCE:
                raise FactContractError(
                    f"{field}: declaration gateway must retain compliance role"
                )
            if definition.value_type != "boolean":
                raise FactContractError(
                    f"{field}: declaration gateway must be boolean"
                )

    def assemble(
        self,
        *,
        program: TradeProgram,
        declarations: tuple[ComplianceGatewayDeclaration, ...],
        evaluated_at: datetime,
    ) -> ComplianceDeclarationInput:
        evaluated_at = require_aware(evaluated_at, "evaluated_at")
        declarations = tuple(declarations)
        declaration_ids = [item.declaration_id for item in declarations]
        if len(declaration_ids) != len(set(declaration_ids)):
            raise FactContractError("duplicate compliance declaration_id")

        case_ids = {case.case_id for case in program.cases}
        declared_case_ids = [item.case_id for item in declarations]
        if len(declared_case_ids) != len(set(declared_case_ids)):
            raise FactContractError(
                "only one active compliance declaration is allowed per case"
            )

        assertions_by_case: dict[str, tuple[FactAssertion, ...]] = {
            case_id: () for case_id in case_ids
        }
        evidence: list[EvidenceDescriptor] = []
        for declaration in declarations:
            if not isinstance(declaration, ComplianceGatewayDeclaration):
                raise TypeError(
                    "declarations must contain ComplianceGatewayDeclaration values"
                )
            if declaration.company_id != program.company.company_id:
                raise FactContractError(
                    f"{declaration.declaration_id}: declaration company "
                    "does not match program"
                )
            if declaration.case_id not in case_ids:
                raise FactContractError(
                    f"{declaration.declaration_id}: unknown case "
                    f"{declaration.case_id}"
                )
            if declaration.declared_at > evaluated_at:
                raise FactContractError(
                    f"{declaration.declaration_id}: declaration is in the future"
                )

            normalized = {
                field: self.catalog.normalize(field, value)
                for field, value in declaration.facts().items()
            }
            evidence_id = f"declaration:{declaration.declaration_id}"
            assertions_by_case[declaration.case_id] = tuple(
                FactAssertion(field, value, (evidence_id,))
                for field, value in sorted(normalized.items())
            )
            evidence.append(
                EvidenceDescriptor(
                    evidence_id=evidence_id,
                    role=EvidenceRole.COMPLIANCE,
                    identifiers=(
                        declaration.case_id,
                        declaration.company_id,
                        DECLARATION_KIND,
                    ),
                    source_ids=(USER_DECLARATION_SOURCE_ID,),
                    generated_at=declaration.declared_at,
                    payload={
                        "attestation_kind": DECLARATION_KIND,
                        "scope": "case",
                        "company_id": declaration.company_id,
                        "case_id": declaration.case_id,
                        "declared_by_role": declaration.declared_by_role,
                        "confirmed": True,
                        "facts": dict(normalized),
                        "limitations": (
                            "scope_gate_only",
                            "not_legal_interpretation",
                            "not_filing_exemption",
                        ),
                    },
                )
            )

        return ComplianceDeclarationInput(
            assertions_by_case=assertions_by_case,
            evidence=tuple(evidence),
        )
