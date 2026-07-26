import unittest

from tradeflow.domain.enums import EvidenceRole
from tradeflow.contracts.evidence import EvidenceDescriptor, EvidenceRequirement
from tradeflow.knowledge.evidence import validate_evidence_contract


class EvidenceContractTests(unittest.TestCase):
    def test_missing_required_role_is_explicit(self) -> None:
        result = validate_evidence_contract(
            [
                EvidenceRequirement(EvidenceRole.USER_TRADE),
                EvidenceRequirement(EvidenceRole.COMPLIANCE),
            ],
            [
                EvidenceDescriptor(
                    "trade:1",
                    EvidenceRole.USER_TRADE,
                    ("CASE-001",),
                )
            ],
        )

        self.assertFalse(result["satisfied"])
        self.assertEqual(["compliance"], result["missing"])

    def test_identifier_matching_is_normalized_but_not_semantically_guessed(self) -> None:
        result = validate_evidence_contract(
            [EvidenceRequirement(EvidenceRole.CALCULATION, ("USD / 2026",))],
            [EvidenceDescriptor("calc:1", EvidenceRole.CALCULATION, ("usd-2026",))],
        )
        self.assertTrue(result["satisfied"])


if __name__ == "__main__":
    unittest.main()
