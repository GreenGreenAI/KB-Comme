"""Recording what produced an answer, precisely enough to catch a mismatch.

§6.2 asks that every calculation reference the snapshot version it used and
store that version with the result, so §9.1's "과거 스냅샷으로 동일 결과를
재현할 수 있다" can be checked rather than asserted.

Snapshots are the easy half: a version names a file that is still on disk, so a
replay reads the same bytes. The knowledge rules are the hard half. They are
edited in place, and a rule whose threshold moved will happily produce a
different answer while the packet schema version stays where it was. Recording
`schema_version` alone therefore lets two materially different answers claim
identical provenance.

So this module fingerprints the rule files themselves. That does not let a
replay *reconstruct* last month's rules — git does that — but it does let a
replay *detect* that it is not comparing like with like, which is the property
a reproducibility claim actually needs. An answer that cannot be reproduced
must say so instead of quietly differing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradeflow.domain.snapshot import SnapshotRef
from tradeflow.domain.snapshot_file import content_hash


@dataclass(frozen=True)
class InputFile:
    """One knowledge file, identified by content rather than by name."""

    role: str
    path: str
    content_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "path": self.path,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class SnapshotVersion:
    source_id: str
    version: str
    content_hash: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "version": self.version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class CalculationVersions:
    """The full input identity of one analysis."""

    formula_version: str
    packet_schema_version: str | None
    knowledge_files: tuple[InputFile, ...]
    snapshots: tuple[SnapshotVersion, ...]
    business_inputs: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "formula_version": self.formula_version,
            "packet_schema_version": self.packet_schema_version,
            "knowledge_files": [item.as_dict() for item in self.knowledge_files],
            "snapshots": [item.as_dict() for item in self.snapshots],
            # Raw company and trade inputs stay out of the provenance block,
            # but their exact normalized identity remains comparable.
            "business_input_hash": content_hash(self.business_inputs),
            # A single value that changes whenever any input above changes, so
            # two answers can be compared without walking the lists.
            "input_fingerprint": self.input_fingerprint(),
            # §6.2's original field, kept so existing readers do not break. It
            # names the market snapshot only, which is why the list above
            # exists.
            "snapshot_version": next(
                (
                    item.version
                    for item in self.snapshots
                    if item.source_id == "ECOS_USD_KRW"
                ),
                None,
            ),
        }

    def input_fingerprint(self) -> str:
        return content_hash(
            {
                "formula_version": self.formula_version,
                "packet_schema_version": self.packet_schema_version,
                "knowledge_files": [item.as_dict() for item in self.knowledge_files],
                "snapshots": [item.as_dict() for item in self.snapshots],
                "business_inputs": self.business_inputs,
            }
        )


def canonical_business_inputs(
    *,
    program: Any,
    baseline_profit: Decimal | None,
    profit_floor: Decimal | None,
    hedge_measures: Iterable[Any],
    evaluated_at: datetime,
    horizon_business_days: int,
) -> dict[str, Any]:
    """Normalize every non-file input that can change an analysis result."""
    company = program.company
    return {
        "program": {
            "program_id": program.program_id,
            "as_of": program.as_of.isoformat(),
            "company": {
                "company_id": company.company_id,
                "name": company.name,
                "country_code": company.country_code,
                "is_sme": company.is_sme,
                "annual_export_usd": _canonical_value(
                    company.annual_export_usd
                ),
                "industry_code": company.industry_code,
                "attributes": _canonical_value(company.attributes),
            },
            "opening_balances": {
                currency: str(amount)
                for currency, amount in sorted(program.opening_balances.items())
            },
            "cases": [
                {
                    "case_id": case.case_id,
                    "direction": case.direction.value,
                    "currency": case.currency,
                    "amount": str(case.amount),
                    "expected_payment_date": (
                        case.expected_payment_date.isoformat()
                    ),
                    "payment_method": case.payment_method.value,
                    "counterparty_country": case.counterparty_country,
                    "confirmed": case.confirmed,
                    "attributes": _canonical_value(case.attributes),
                }
                for case in program.cases
            ],
        },
        "calculation_parameters": {
            "evaluated_at": evaluated_at.isoformat(),
            "horizon_business_days": horizon_business_days,
            "baseline_profit": _canonical_value(baseline_profit),
            "profit_floor": _canonical_value(profit_floor),
            # Order is material: the orchestrator uses the first usable
            # measure, so sorting would hide a result-changing input.
            "hedge_measures": [
                {
                    "measure_id": measure.measure_id,
                    "category": measure.category.value,
                    "kind": measure.kind.value,
                    "status": measure.status.value,
                    "status_reasons": list(measure.status_reasons),
                    "contract_rate": _canonical_value(measure.contract_rate),
                    "cost_rate": _canonical_value(measure.cost_rate),
                    "source_ids": list(measure.source_ids),
                }
                for measure in hedge_measures
            ],
        },
    }


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(
        f"unsupported business input value {type(value).__name__}"
    )


def fingerprint_file(path: Path | str, *, role: str, relative_to: Path) -> InputFile:
    """Hash one knowledge file, naming it by its place in the repository.

    The path is recorded relative to the repository root so a fingerprint taken
    on a developer machine matches one taken in CI; an absolute path would make
    every environment look like a different rule set.
    """
    path = Path(path).resolve()
    try:
        name = path.relative_to(relative_to.resolve()).as_posix()
    except ValueError:
        name = path.name
    return InputFile(
        role=role,
        path=name,
        content_hash="sha256:" + _sha256(path),
    )


def fingerprint_knowledge(
    *,
    repo_root: Path,
    source_registry: Path,
    rulepacks: Iterable[Path],
    fact_catalog: Path | None = None,
) -> tuple[InputFile, ...]:
    """Fingerprint every file that can change what the rules decide.

    Document catalogs are pulled in by path from inside a rulepack, so they are
    resolved here too: a changed document list changes the recommended actions
    without touching any file named in the call.
    """
    files: list[InputFile] = [
        fingerprint_file(source_registry, role="source_registry", relative_to=repo_root)
    ]
    if fact_catalog is not None:
        files.append(
            fingerprint_file(fact_catalog, role="fact_catalog", relative_to=repo_root)
        )

    seen: set[Path] = set()
    for pack in rulepacks:
        pack = Path(pack)
        files.append(fingerprint_file(pack, role="rulepack", relative_to=repo_root))
        for catalog in _referenced_catalogs(pack):
            if catalog in seen:
                continue
            seen.add(catalog)
            files.append(
                fingerprint_file(
                    catalog, role="document_catalog", relative_to=repo_root
                )
            )

    return tuple(sorted(files, key=lambda item: (item.role, item.path)))


def snapshot_versions(refs: Iterable[SnapshotRef | None]) -> tuple[SnapshotVersion, ...]:
    """Record the snapshots an analysis actually read.

    A snapshot that was not read is left out rather than recorded as null: the
    answer did not depend on it, and listing it would suggest otherwise.
    """
    versions = [
        SnapshotVersion(ref.source_id, ref.version, ref.content_hash)
        for ref in refs
        if ref is not None
    ]
    return tuple(sorted(versions, key=lambda item: item.source_id))


def _referenced_catalogs(pack: Path) -> tuple[Path, ...]:
    import json

    try:
        data = json.loads(pack.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(data, Mapping):
        return ()
    return tuple(
        (pack.parent / relative).resolve()
        for relative in data.get("document_catalogs", ())
        if isinstance(relative, str)
    )


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
