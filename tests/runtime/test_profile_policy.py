import unittest

from tradeflow.contracts.profile_policy import UserProfileFacts
from tradeflow.runtime.profile_policy import evaluate_profile_policy


class ProfilePolicyTests(unittest.TestCase):
    def test_verified_fact_requires_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires evidence_id"):
            UserProfileFacts.from_mapping({
                "facts": [{
                    "field": "trade.export_volume.trailing_12m_usd",
                    "value": "10",
                    "provenance": "verified",
                }]
            })

    def test_verified_export_history_can_derive_exporter_role(self) -> None:
        result = evaluate_profile_policy({
            "company_size": "small",
            "trade_maturity_months": 24,
            "facts": [{
                "field": "trade.export_volume.trailing_12m_usd",
                "value": "100000",
                "provenance": "verified",
                "evidence_id": "trade-history:1",
            }],
        }).as_dict()

        self.assertEqual(result["primary_type"], "existing_exporter_sme")
        self.assertIn("exporter", result["axes"]["trade_role"])

    def test_user_role_does_not_create_fx_risk(self) -> None:
        result = evaluate_profile_policy({
            "user_role": "finance_manager",
            "existing_hedge_ratio": "0",
        }).as_dict()

        self.assertNotIn("fx_sensitive", result["secondary_types"])

    def test_missing_consent_prevents_capability_execution(self) -> None:
        result = evaluate_profile_policy({
            "primary_type": "existing_exporter_sme",
            "consents": [],
        }).as_dict()

        self.assertEqual(result["executed_capabilities"], [])
        self.assertEqual(result["fallback"], "manual_evidence_request")
        self.assertIn(
            "company_trade_data.read",
            result["missing_consents"],
        )

    def test_classification_never_claims_product_eligibility(self) -> None:
        result = evaluate_profile_policy({
            "primary_type": "potential_exporter",
            "eligibility_evidence": [],
        }).as_dict()

        self.assertEqual(result["decision_status"], "missing_information")
        self.assertNotIn("eligible", result["claims"])


if __name__ == "__main__":
    unittest.main()
