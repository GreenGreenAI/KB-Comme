import re
import unicodedata
from collections.abc import Iterable

from tradeflow.contracts.evidence import EvidenceDescriptor, EvidenceRequirement


def normalize_identifier(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def validate_evidence_contract(
    requirements: Iterable[EvidenceRequirement],
    descriptors: Iterable[EvidenceDescriptor],
) -> dict[str, object]:
    """Validate typed evidence coverage without semantic keyword guessing."""
    available: dict[str, set[str]] = {}
    for descriptor in descriptors:
        available.setdefault(descriptor.role.value, set()).update(
            normalize_identifier(value) for value in descriptor.identifiers
        )

    fulfilled: list[str] = []
    missing: list[str] = []
    checked: list[str] = []

    for requirement in requirements:
        key = requirement.role.value
        checked.append(key)
        candidates = available.get(key, set())
        required_ids = {normalize_identifier(value) for value in requirement.identifiers}
        covered = bool(candidates) and (not required_ids or required_ids <= candidates)
        if covered:
            fulfilled.append(key)
        elif requirement.required:
            missing.append(key)

    return {
        "satisfied": not missing,
        "checked": checked,
        "fulfilled": fulfilled,
        "missing": missing,
    }
