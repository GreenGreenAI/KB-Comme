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
            "company_size": "small",
            "trade_maturity_months": 24,
            "facts": [{
                "field": "trade.export_volume.trailing_12m_usd",
                "value": "100000",
                "provenance": "verified",
                "evidence_id": "trade-history:missing-consent",
            }],
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
            "trade_roles": ["potential_exporter"],
            "export_volume_trailing_12m_usd": "0",
            "eligibility_evidence": [],
        }).as_dict()

        self.assertEqual(result["decision_status"], "missing_information")
        self.assertNotIn("eligible", result["claims"])

    def test_input_primary_type_cannot_override_classification(self) -> None:
        result = evaluate_profile_policy({
            "primary_type": "existing_exporter_sme",
            "consents": ["company_trade_data.read"],
        }).as_dict()

        self.assertIsNone(result["primary_type"])
        self.assertNotIn("trade_history.lookup.v1", result["route_capabilities"])

    def test_consent_authorizes_but_does_not_claim_execution(self) -> None:
        result = evaluate_profile_policy({
            "company_size": "small",
            "trade_maturity_months": 24,
            "facts": [{
                "field": "trade.export_volume.trailing_12m_usd",
                "value": "100000",
                "provenance": "verified",
                "evidence_id": "trade-history:authorized",
            }],
            "consents": ["company_trade_data.read"],
        }).as_dict()

        self.assertIn("trade_history.lookup.v1", result["authorized_capabilities"])
        self.assertEqual(result["executed_capabilities"], [])

    def test_expired_export_fact_does_not_classify_exporter(self) -> None:
        result = evaluate_profile_policy({
            "as_of": "2026-08-01T12:00:00+09:00",
            "company_size": "small",
            "trade_maturity_months": 24,
            "facts": [{
                "field": "trade.export_volume.trailing_12m_usd",
                "value": "100000",
                "provenance": "verified",
                "evidence_id": "trade-history:expired",
                "valid_until": "2026-08-01T00:00:00+09:00",
            }],
        }).as_dict()

        self.assertIsNone(result["primary_type"])
        self.assertEqual(result["fact_status"], "stale")
        self.assertTrue(result["review_required"])

    def test_verified_country_policy_requires_current_evidence(self) -> None:
        result = evaluate_profile_policy({
            "as_of": "2026-08-01T12:00:00+09:00",
            "country_policy": {
                "country": "XZ",
                "status": "restricted",
                "provenance": "verified",
                "valid_until": "2026-08-02T00:00:00+09:00",
            },
        }).as_dict()

        self.assertNotIn("high_risk_country_trade", result["secondary_types"])
        self.assertIn("country_policy.evidence_id", result["missing_fields"])
        self.assertIn("country_policy.refresh.v1", result["route_capabilities"])
        self.assertTrue(result["review_required"])

    def test_invalid_as_of_year_is_not_an_error(self) -> None:
        result = evaluate_profile_policy({
            "established_year": 2024,
            "as_of_year": "unknown",
            "trade_maturity_months": 3,
        }).as_dict()

        self.assertIsNone(result["primary_type"])


if __name__ == "__main__":
    unittest.main()
