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
        self.fact_specs = {
            item["field"]: item
            for item in _json(KNOWLEDGE_ROOT / "fact_catalog.json")["facts"]
        }
        self.fact_fields = set(self.fact_specs)
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

        regulatory_chain = {
            "FX_TRANSACTION_ACT_2026_01_02",
            "FX_TRANSACTION_DECREE_2026_04_28",
            "FX_TRANSACTION_REGULATION_2026_88",
        }
        operational_sources = {
            "BOK_FX_REPORTING_GUIDE",
            "BOK_FX_MUTUAL_ACCOUNT_FAQ",
        }
        rulepack = _json(
            KNOWLEDGE_ROOT / "rulepacks" / "fx_compliance_mvp.json"
        )
        for rule in rulepack["rules"]:
            with self.subTest(rule_id=rule["rule_id"]):
                source_ids = set(rule["source_ids"])
                self.assertTrue(regulatory_chain <= source_ids)
                self.assertEqual(
                    1,
                    len(source_ids & operational_sources),
                )
                self.assertEqual(
                    regulatory_chain | (source_ids & operational_sources),
                    source_ids,
                )

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

    def test_chapter5_exception_catalog_is_complete_and_matches_fact_enums(
        self,
    ) -> None:
        catalog = _json(
            KNOWLEDGE_ROOT / "exception_catalogs" / "fx_chapter5.json"
        )
        sections = {item["article"]: item for item in catalog["sections"]}
        self.assertEqual(
            {"5-4", "5-8", "5-10", "5-11"},
            set(sections),
        )
        self.assertEqual(
            {"5-4": 15, "5-8": 4, "5-10": 32, "5-11": 14},
            {
                article: len(section["exceptions"])
                for article, section in sections.items()
            },
        )
        self.assertEqual("explanation_only", catalog["llm_role"])

        field_by_article = {
            "5-4": "payment.netting.exception_category",
            "5-8": "trade.extended_payment_exception_category",
            "5-10": "payment.third_party.exception_category",
            "5-11": "payment.nonbank.exception_category",
        }
        all_codes: set[str] = set()
        for article, field in field_by_article.items():
            with self.subTest(article=article):
                exceptions = sections[article]["exceptions"]
                codes = {item["code"] for item in exceptions}
                self.assertEqual(len(exceptions), len(codes))
                self.assertFalse(all_codes & codes)
                all_codes |= codes
                self.assertEqual(
                    codes | {"none", "unknown"},
                    set(self.fact_specs[field]["allowed_values"]),
                )
                self.assertTrue(
                    all(
                        item["automation_level"]
                        in {
                            "deterministic_with_evidence",
                            "expert_confirmation_required",
                        }
                        for item in exceptions
                    )
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

    def _fx_decisions(self, facts: dict) -> dict:
        repository = self._repository("fx_compliance_mvp.json")
        freshness = {
            source_id: Freshness.FRESH for source_id in repository.sources
        }
        return {
            decision.rule_id: decision
            for decision in repository.evaluate(
                topic="fx_compliance",
                facts=facts,
                as_of=date(2026, 7, 27),
                source_freshness=freshness,
            )
        }

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
                "payment.netting.exception_category": "none",
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

    def test_named_netting_exception_does_not_trigger_filing_candidate(self) -> None:
        decisions = self._fx_decisions(
            {
                "payment.is_netting": True,
                "payment.netting.party_count": 2,
                "payment.netting.uses_center": False,
                "payment.netting.smaller_claim_usd": 6000,
                "payment.netting.exception_category": "article_5_4_5",
            }
        )
        bilateral = decisions["FX_BILATERAL_NETTING_BANK_REPORT_CANDIDATE"]
        self.assertEqual(DecisionStatus.NOT_ELIGIBLE, bilateral.status)

    def test_two_party_netting_through_center_routes_to_bok(self) -> None:
        decisions = self._fx_decisions(
            {
                "payment.is_netting": True,
                "payment.netting.party_count": 2,
                "payment.netting.uses_center": True,
                "payment.netting.smaller_claim_usd": 6000,
                "payment.netting.exception_category": "none",
            }
        )
        center = decisions["FX_NETTING_CENTER_BOK_FILING_CANDIDATE"]
        bilateral = decisions["FX_BILATERAL_NETTING_BANK_REPORT_CANDIDATE"]
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            center.status,
        )
        self.assertEqual(DecisionStatus.NOT_ELIGIBLE, bilateral.status)

    def test_third_party_payment_amount_boundaries_route_to_right_authority(
        self,
    ) -> None:
        bank_rule = "FX_THIRD_PARTY_PAYMENT_BANK_FILING_CANDIDATE"
        bok_rule = "FX_THIRD_PARTY_PAYMENT_BOK_FILING_CANDIDATE"
        expected = {
            5000: (DecisionStatus.NOT_ELIGIBLE, DecisionStatus.NOT_ELIGIBLE),
            5000.01: (
                DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
                DecisionStatus.NOT_ELIGIBLE,
            ),
            10000: (
                DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
                DecisionStatus.NOT_ELIGIBLE,
            ),
            10000.01: (
                DecisionStatus.NOT_ELIGIBLE,
                DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            ),
        }

        for amount, statuses in expected.items():
            with self.subTest(amount=amount):
                decisions = self._fx_decisions(
                    {
                        "payment.is_third_party": True,
                        "payment.third_party.amount_usd": amount,
                        "payment.third_party.exception_category": (
                            "article_5_10_1" if amount <= 5000 else "none"
                        ),
                    }
                )
                self.assertEqual(statuses[0], decisions[bank_rule].status)
                self.assertEqual(statuses[1], decisions[bok_rule].status)

    def test_third_party_exception_does_not_trigger_filing_candidate(self) -> None:
        decisions = self._fx_decisions(
            {
                "payment.is_third_party": True,
                "payment.third_party.amount_usd": 15000,
                "payment.third_party.exception_category": "article_5_10_22",
            }
        )
        bok = decisions["FX_THIRD_PARTY_PAYMENT_BOK_FILING_CANDIDATE"]
        self.assertEqual(DecisionStatus.NOT_ELIGIBLE, bok.status)

    def test_missing_third_party_exception_classification_is_not_guessed(
        self,
    ) -> None:
        decisions = self._fx_decisions(
            {
                "payment.is_third_party": True,
                "payment.third_party.amount_usd": 15000,
            }
        )
        bok = decisions["FX_THIRD_PARTY_PAYMENT_BOK_FILING_CANDIDATE"]
        self.assertEqual(DecisionStatus.INSUFFICIENT_INFORMATION, bok.status)
        self.assertIn(
            "payment.third_party.exception_category",
            bok.missing_fields,
        )

    def test_nonbank_payment_without_exception_requires_draft_review(self) -> None:
        decisions = self._fx_decisions(
            {
                "payment.uses_foreign_exchange_bank": False,
                "payment.direction": "pay",
                "payment.nonbank.exception_category": "none",
            }
        )
        nonbank = decisions["FX_NONBANK_PAYMENT_BOK_FILING_CANDIDATE"]
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            nonbank.status,
        )
        self.assertEqual(
            "bank_of_korea",
            nonbank.candidate_outcome["authority"],
        )

    def test_nonbank_receipt_or_documented_exception_is_not_filing_candidate(
        self,
    ) -> None:
        cases = (
            {
                "payment.uses_foreign_exchange_bank": False,
                "payment.direction": "receive",
                "payment.nonbank.exception_category": "article_5_11_receipt",
            },
            {
                "payment.uses_foreign_exchange_bank": False,
                "payment.direction": "pay",
                "payment.nonbank.exception_category": "article_5_11_8",
            },
        )
        for facts in cases:
            with self.subTest(facts=facts):
                decisions = self._fx_decisions(facts)
                nonbank = decisions["FX_NONBANK_PAYMENT_BOK_FILING_CANDIDATE"]
                self.assertEqual(DecisionStatus.NOT_ELIGIBLE, nonbank.status)

    def test_documented_extended_payment_exception_is_not_filing_candidate(
        self,
    ) -> None:
        decisions = self._fx_decisions(
            {
                "trade.direction": "export",
                "trade.contract_amount_usd": 100000.01,
                "trade.days_before_shipment": 366,
                "trade.extended_payment_exception_category": (
                    "article_5_8_aircraft"
                ),
            }
        )
        export = decisions["FX_EXPORT_ADVANCE_RECEIPT_BOK_FILING_CANDIDATE"]
        self.assertEqual(DecisionStatus.NOT_ELIGIBLE, export.status)

    def test_unfiled_bilateral_mutual_account_routes_to_designated_bank(
        self,
    ) -> None:
        decisions = self._fx_decisions(
            {
                "payment.uses_mutual_account": True,
                "payment.mutual_account.party_count": 2,
                "payment.mutual_account.opening_filing_completed": False,
            }
        )
        opening = decisions[
            "FX_MUTUAL_ACCOUNT_OPENING_BANK_FILING_CANDIDATE"
        ]
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            opening.status,
        )
        self.assertEqual(
            "designated_foreign_exchange_bank",
            opening.candidate_outcome["authority"],
        )
        self.assertIn("BOK_FX_MUTUAL_ACCOUNT_FAQ", opening.source_ids)

    def test_multilateral_mutual_account_is_reclassified(self) -> None:
        decisions = self._fx_decisions(
            {
                "payment.uses_mutual_account": True,
                "payment.mutual_account.party_count": 3,
            }
        )
        reclassification = decisions[
            "FX_MUTUAL_ACCOUNT_MULTILATERAL_RECLASSIFICATION_CANDIDATE"
        ]
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            reclassification.status,
        )
        self.assertEqual(
            "reclassify_as_multilateral_netting",
            reclassification.candidate_outcome["action"],
        )

    def test_mutual_account_entry_deadline_breach_is_not_inferred(self) -> None:
        rule_id = "FX_MUTUAL_ACCOUNT_ENTRY_DEADLINE_BREACH_CANDIDATE"
        missing = self._fx_decisions(
            {"payment.uses_mutual_account": True}
        )[rule_id]
        self.assertEqual(
            DecisionStatus.INSUFFICIENT_INFORMATION,
            missing.status,
        )
        self.assertIn(
            "payment.mutual_account.entry_deadline_breached",
            missing.missing_fields,
        )

        breached = self._fx_decisions(
            {
                "payment.uses_mutual_account": True,
                "payment.mutual_account.entry_deadline_breached": True,
            }
        )[rule_id]
        self.assertEqual(
            DecisionStatus.EXPERT_CONFIRMATION_REQUIRED,
            breached.status,
        )

    def test_mutual_account_retention_boundary_is_five_years(self) -> None:
        rule_id = "FX_MUTUAL_ACCOUNT_RETENTION_GAP_CANDIDATE"
        for years, status in (
            (4, DecisionStatus.EXPERT_CONFIRMATION_REQUIRED),
            (5, DecisionStatus.NOT_ELIGIBLE),
        ):
            with self.subTest(years=years):
                decision = self._fx_decisions(
                    {
                        "payment.uses_mutual_account": True,
                        "payment.mutual_account.records_retention_years": years,
                    }
                )[rule_id]
                self.assertEqual(status, decision.status)

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
