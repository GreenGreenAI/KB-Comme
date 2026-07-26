import json
import unittest
from datetime import date, datetime
from pathlib import Path

from tradeflow.domain.enums import DecisionStatus, Freshness
from tradeflow.domain.snapshot_file import content_hash
from tradeflow.knowledge.repository import KnowledgeRepository


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
REGISTRY_PATH = KNOWLEDGE_ROOT / "source_registry.json"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class KnowledgeAssetIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = _json(REGISTRY_PATH)
        self.sources = {
            item["source_id"]: item for item in self.registry["sources"]
        }
        self.fact_fields = {
            item["field"]
            for item in _json(KNOWLEDGE_ROOT / "fact_catalog.json")["facts"]
        }
        self.rule_paths = sorted((KNOWLEDGE_ROOT / "rulepacks").glob("*.json"))
        self.claim_ids: set[str] = set()
        for path in (KNOWLEDGE_ROOT / "extracts").glob("*.json"):
            for claim in _json(path)["claims"]:
                self.assertNotIn(claim["claim_id"], self.claim_ids)
                self.claim_ids.add(claim["claim_id"])

    def test_registered_extracts_are_verified_and_hash_matched(self) -> None:
        extracted_sources = [
            source for source in self.sources.values() if source.get("extract_path")
        ]
        self.assertGreaterEqual(len(extracted_sources), 6)

        for source in extracted_sources:
            with self.subTest(source_id=source["source_id"]):
                self.assertTrue(source["official"])
                self.assertTrue(source["verified"])
                self.assertTrue(source["freshness_required"])
                retrieved = datetime.fromisoformat(source["retrieved_at"])
                self.assertIsNotNone(retrieved.tzinfo)

                extract_path = PROJECT_ROOT / source["extract_path"]
                extract = _json(extract_path)
                self.assertEqual(source["source_id"], extract["source_id"])
                self.assertEqual(source["url"], extract["document"]["official_url"])
                self.assertEqual(source["content_hash"], content_hash(extract))

    def test_fx_rules_use_the_verified_current_regulatory_chain(self) -> None:
        current = self.sources["FX_TRANSACTION_REGULATION_2026_88"]
        self.assertEqual("2026-07-06", current["effective_from"])
        extract = _json(PROJECT_ROOT / current["extract_path"])
        self.assertEqual(
            "재정경제부고시 제2026-88호",
            extract["document"]["instrument"],
        )

        expected_chain = {
            "FX_TRANSACTION_ACT_2026_01_02",
            "FX_TRANSACTION_DECREE_2026_04_28",
            "FX_TRANSACTION_REGULATION_2026_88",
            "BOK_FX_REPORTING_GUIDE",
        }
        rulepack = _json(
            KNOWLEDGE_ROOT / "rulepacks" / "fx_compliance_mvp.json"
        )
        for rule in rulepack["rules"]:
            self.assertEqual(expected_chain, set(rule["source_ids"]))

    def test_rules_reference_registered_sources_and_cataloged_facts(self) -> None:
        rule_ids: set[str] = set()
        for path in self.rule_paths:
            rulepack = _json(path)
            for rule in rulepack["rules"]:
                with self.subTest(rule_id=rule["rule_id"]):
                    self.assertNotIn(rule["rule_id"], rule_ids)
                    rule_ids.add(rule["rule_id"])
                    self.assertTrue(set(rule["source_ids"]) <= set(self.sources))
                    fields = {
                        condition["field"] for condition in rule["conditions"]
                    }
                    self.assertTrue(fields <= self.fact_fields)
                    if path.name != "demo_trade_support.json":
                        self.assertTrue(rule["source_claim_ids"])
                        self.assertTrue(
                            set(rule["source_claim_ids"]) <= self.claim_ids
                        )

    def test_new_rulepacks_remain_draft_until_cross_role_review(self) -> None:
        for name in ("ksure_mvp_candidates.json", "fx_compliance_mvp.json"):
            rulepack = _json(KNOWLEDGE_ROOT / "rulepacks" / name)
            self.assertEqual("draft", rulepack["status"])
            self.assertTrue(
                all(not rule["production_ready"] for rule in rulepack["rules"])
            )

    def test_all_rulepacks_can_be_loaded_by_the_repository(self) -> None:
        for path in self.rule_paths:
            with self.subTest(rulepack=path.name):
                repository = KnowledgeRepository.from_json(REGISTRY_PATH, path)
                self.assertEqual(
                    len(_json(path)["rules"]),
                    len(repository.rules),
                )
                for rule in repository.rules.values():
                    if path.name != "demo_trade_support.json":
                        self.assertTrue(rule.source_claim_ids)
                        self.assertTrue(rule.candidate_outcome)


class CuratedRuleSafetyTests(unittest.TestCase):
    def _repository(self, name: str) -> KnowledgeRepository:
        return KnowledgeRepository.from_json(
            REGISTRY_PATH,
            KNOWLEDGE_ROOT / "rulepacks" / name,
        )

    def test_complete_netting_candidate_still_requires_draft_review(self) -> None:
        repository = self._repository("fx_compliance_mvp.json")
        freshness = {
            source_id: Freshness.FRESH for source_id in repository.sources
        }
        decisions = repository.evaluate(
            topic="fx_compliance",
            facts={
                "payment.is_netting": True,
                "payment.netting.party_count": 2,
                "payment.netting.uses_center": False,
                "payment.netting.smaller_claim_usd": 6000,
                "payment.netting.exception_applies": False,
            },
            as_of=date(2026, 7, 27),
            source_freshness=freshness,
        )
        bilateral = next(
            item
            for item in decisions
            if item.rule_id == "FX_BILATERAL_NETTING_BANK_REPORT_CANDIDATE"
        )
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            bilateral.status,
        )
        self.assertIn(
            "draft rule: official confirmation required",
            bilateral.reasons,
        )
        self.assertEqual(
            "foreign_exchange_bank",
            bilateral.candidate_outcome["authority"],
        )
        self.assertIn("BOK_BILATERAL_NETTING_REPORT", bilateral.source_claim_ids)
        procedure = repository.procedure_for(bilateral.rule_id)
        self.assertIsNotNone(procedure)
        assert procedure is not None
        self.assertEqual(
            "report",
            procedure["candidate_outcome"]["action"],
        )
        self.assertIn(
            "BOK_BILATERAL_NETTING_REPORT",
            procedure["source_claim_ids"],
        )

    def test_missing_ksure_grade_is_not_guessed(self) -> None:
        repository = self._repository("ksure_mvp_candidates.json")
        freshness = {
            source_id: Freshness.FRESH for source_id in repository.sources
        }
        decisions = repository.evaluate(
            topic="trade_support_case",
            facts={
                "company.is_domestic": True,
                "trade.direction": "export",
                "trade.payment_term_days": 180,
            },
            as_of=date(2026, 7, 27),
            source_freshness=freshness,
        )
        short_term = next(
            item
            for item in decisions
            if item.rule_id
            == "KSURE_SHORT_TERM_EXPORT_POSTSHIP_INDIVIDUAL_CANDIDATE"
        )
        self.assertEqual(
            DecisionStatus.INSUFFICIENT_INFORMATION,
            short_term.status,
        )
        self.assertIn(
            "company.ksure_exporter_grade",
            short_term.missing_fields,
        )


if __name__ == "__main__":
    unittest.main()
