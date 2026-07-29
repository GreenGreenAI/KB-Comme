"""Evidence-bound fact assembly for case-level rule evaluation.

Facts used by regulation and eligibility rules are not free-form attributes.
Every supplemental fact must exist in the catalog, satisfy its declared type,
and cite evidence carrying the catalog's required role.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from tradeflow.contracts.evidence import EvidenceDescriptor
from tradeflow.domain.enums import EvidenceRole
from tradeflow.domain.models import TradeCase, TradeProgram


class FactContractError(ValueError):
    """A fact is unknown, malformed, conflicting, or lacks suitable evidence."""


@dataclass(frozen=True)
class FactDefinition:
    field: str
    value_type: str
    evidence_role: EvidenceRole
    allowed_values: tuple[Any, ...] = ()


@dataclass(frozen=True)
class FactAssertion:
    field: str
    value: Any
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        evidence_ids = tuple(self.evidence_ids)
        if not evidence_ids:
            raise FactContractError(f"{self.field}: at least one evidence_id is required")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise FactContractError(f"{self.field}: duplicate evidence_id values")
        object.__setattr__(self, "evidence_ids", evidence_ids)


@dataclass(frozen=True)
class FactBundle:
    case_id: str
    facts: Mapping[str, Any]
    evidence_ids_by_fact: Mapping[str, tuple[str, ...]]


class FactCatalog:
    def __init__(self, definitions: Iterable[FactDefinition]) -> None:
        items = tuple(definitions)
        definitions = {item.field: item for item in items}
        if len(definitions) != len(items):
            raise FactContractError("fact catalog contains duplicate fields")
        self.definitions = MappingProxyType(definitions)

    @classmethod
    def from_json(cls, path: Path | str) -> FactCatalog:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if document.get("schema_version") != "1.0":
            raise FactContractError("unsupported fact catalog schema_version")
        return cls(
            FactDefinition(
                field=item["field"],
                value_type=item["type"],
                evidence_role=EvidenceRole(item["evidence_role"]),
                allowed_values=tuple(item.get("allowed_values", ())),
            )
            for item in document["facts"]
        )

    def normalize(self, field: str, value: Any) -> Any:
        definition = self.definitions.get(field)
        if definition is None:
            raise FactContractError(f"unknown fact: {field}")
        value_type = definition.value_type
        if value_type == "boolean":
            if not isinstance(value, bool):
                raise FactContractError(f"{field}: expected boolean")
            normalized = value
        elif value_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise FactContractError(f"{field}: expected integer")
            normalized = value
        elif value_type == "decimal":
            if isinstance(value, bool):
                raise FactContractError(f"{field}: expected decimal")
            try:
                normalized = Decimal(str(value))
            except (InvalidOperation, ValueError):
                raise FactContractError(f"{field}: expected decimal") from None
            if not normalized.is_finite():
                raise FactContractError(f"{field}: decimal must be finite")
        elif value_type in {"enum", "string"}:
            if not isinstance(value, str) or not value:
                raise FactContractError(f"{field}: expected non-empty string")
            normalized = value
        else:
            raise FactContractError(
                f"{field}: unsupported catalog type {value_type!r}"
            )
        if definition.allowed_values and normalized not in definition.allowed_values:
            allowed = ", ".join(str(item) for item in definition.allowed_values)
            raise FactContractError(f"{field}: expected one of {allowed}")
        return normalized


class FactAssembler:
    """Build one immutable, evidence-bound fact set for a trade case."""

    _CORE_FIELDS = {
        "company.is_domestic",
        "trade.direction",
        "trade.currency",
        "trade.contract_amount_usd",
        "program.has_export",
    }

    def __init__(self, catalog: FactCatalog) -> None:
        self.catalog = catalog

    def assemble(
        self,
        *,
        program: TradeProgram,
        case: TradeCase,
        assertions: Iterable[FactAssertion],
        evidence: Iterable[EvidenceDescriptor],
    ) -> FactBundle:
        if case not in program.cases:
            raise FactContractError(f"{case.case_id}: case is not in program")
        evidence = tuple(evidence)
        evidence_by_id = {item.evidence_id: item for item in evidence}
        if len(evidence_by_id) != len(evidence):
            raise FactContractError("evidence contains duplicate evidence_id values")

        trade_evidence_id = f"trade:{program.program_id}"
        calculation_evidence_id = f"calculation:{program.program_id}"
        self._require_role(
            "trade.direction",
            (trade_evidence_id,),
            evidence_by_id,
        )
        facts: dict[str, Any] = {}
        provenance: dict[str, tuple[str, ...]] = {}

        core = {
            "company.is_domestic": (
                program.company.country_code.upper() == "KR",
                (trade_evidence_id,),
            ),
            "trade.direction": (case.direction.value, (trade_evidence_id,)),
            "trade.currency": (case.currency, (trade_evidence_id,)),
            "program.has_export": (
                any(item.direction.value == "export" for item in program.cases),
                (trade_evidence_id,),
            ),
        }
        if case.currency == "USD":
            core["trade.contract_amount_usd"] = (
                case.amount,
                (calculation_evidence_id,),
            )

        for field, (value, evidence_ids) in core.items():
            self._require_role(field, evidence_ids, evidence_by_id)
            facts[field] = self.catalog.normalize(field, value)
            provenance[field] = evidence_ids

        assertions = tuple(assertions)
        fields = [item.field for item in assertions]
        if len(set(fields)) != len(fields):
            raise FactContractError("assertions contain duplicate fact fields")
        for assertion in assertions:
            if assertion.field in self._CORE_FIELDS:
                raise FactContractError(
                    f"{assertion.field}: core fact cannot be overridden"
                )
            self._require_role(
                assertion.field,
                assertion.evidence_ids,
                evidence_by_id,
            )
            normalized = self.catalog.normalize(
                assertion.field, assertion.value
            )
            self._require_attestation(
                case.case_id,
                assertion.field,
                normalized,
                assertion.evidence_ids,
                evidence_by_id,
            )
            facts[assertion.field] = normalized
            provenance[assertion.field] = assertion.evidence_ids

        return FactBundle(
            case_id=case.case_id,
            facts=MappingProxyType(facts),
            evidence_ids_by_fact=MappingProxyType(provenance),
        )

    def _require_role(
        self,
        field: str,
        evidence_ids: tuple[str, ...],
        evidence_by_id: Mapping[str, EvidenceDescriptor],
    ) -> None:
        definition = self.catalog.definitions.get(field)
        if definition is None:
            raise FactContractError(f"unknown fact: {field}")
        missing = [item for item in evidence_ids if item not in evidence_by_id]
        if missing:
            raise FactContractError(
                f"{field}: unknown evidence_ids: {', '.join(missing)}"
            )
        accepted_roles = {definition.evidence_role}
        if definition.evidence_role is EvidenceRole.SUPPORT_ELIGIBILITY:
            # A company declaration may be used to produce a candidate result,
            # but it must remain distinguishable from authoritative eligibility
            # evidence. The pipeline adds a mandatory review reason whenever
            # this weaker role participates.
            accepted_roles.add(EvidenceRole.USER_DECLARATION)
        if not any(
            evidence_by_id[item].role in accepted_roles
            for item in evidence_ids
        ):
            raise FactContractError(
                f"{field}: requires {definition.evidence_role.value} evidence"
            )

    def _require_attestation(
        self,
        case_id: str,
        field: str,
        value: Any,
        evidence_ids: tuple[str, ...],
        evidence_by_id: Mapping[str, EvidenceDescriptor],
    ) -> None:
        for evidence_id in evidence_ids:
            descriptor = evidence_by_id[evidence_id]
            if case_id not in descriptor.identifiers:
                continue
            claims = descriptor.payload.get("facts")
            if not isinstance(claims, Mapping) or field not in claims:
                continue
            try:
                claimed = self.catalog.normalize(field, claims[field])
            except FactContractError:
                continue
            if claimed == value:
                return
        raise FactContractError(
            f"{field}: cited evidence does not attest the value for {case_id}"
        )
