import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "knowledge"
    / "schemas"
    / "observed_forward_quote_history.schema.json"
)


class ObservedForwardQuoteHistorySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.record = cls.schema["$defs"]["quote_record"]

    def test_dataset_is_explicitly_tenant_private_and_closed(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(
            "tenant_private_financial",
            self.schema["properties"]["retention_class"]["const"],
        )
        self.assertEqual(1, self.schema["properties"]["records"]["minItems"])
        self.assertIn("tenant_id", self.schema["required"])
        self.assertFalse(self.record["additionalProperties"])

    def test_promotion_identity_and_provenance_are_mandatory(self) -> None:
        required = set(self.record["required"])
        self.assertTrue(
            {
                "company_id",
                "case_ids",
                "provider_id",
                "observed_at",
                "valid_until",
                "settlement_date",
                "quote_basis",
                "provider_verified",
                "company_applicable",
                "origin_spot_snapshot",
                "evidence_content_hash",
            }
            <= required
        )
        properties = self.record["properties"]
        self.assertEqual(
            "observed_forward_quote",
            properties["quote_basis"]["const"],
        )
        self.assertTrue(properties["provider_verified"]["const"])
        self.assertTrue(properties["company_applicable"]["const"])

    def test_money_uses_decimal_strings_and_never_json_floats(self) -> None:
        properties = self.record["properties"]
        for field in (
            "notional_min",
            "notional_max",
            "contract_rate",
            "cost_rate",
        ):
            with self.subTest(field=field):
                self.assertIn("$ref", properties[field])


if __name__ == "__main__":
    unittest.main()
