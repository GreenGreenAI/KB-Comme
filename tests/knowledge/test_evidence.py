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

    def test_stale_or_rejected_descriptor_does_not_satisfy_coverage(self) -> None:
        for usability in ("stale", "rejected"):
            with self.subTest(usability=usability):
                result = validate_evidence_contract(
                    [EvidenceRequirement(EvidenceRole.SUPPORT_ELIGIBILITY)],
                    [
                        EvidenceDescriptor(
                            f"eligibility:{usability}",
                            EvidenceRole.SUPPORT_ELIGIBILITY,
                            ("CASE-001",),
                            payload={"usability": usability},
                        )
                    ],
                )
                self.assertFalse(result["satisfied"])
                self.assertEqual(["support_eligibility"], result["missing"])


if __name__ == "__main__":
    unittest.main()
