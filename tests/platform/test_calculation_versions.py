"""Reproducibility of an answer, checked rather than asserted (§6.2, §9.1).

The claim is "과거 스냅샷으로 동일 결과를 재현할 수 있다". A version block that
cannot tell two different rule sets apart does not support that claim, so these
tests are mostly about what makes the recorded version *change*.
"""

import json
import shutil
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import (
    FACT_CATALOG,
    REPO_ROOT,
    RULEPACKS,
    SOURCE_REGISTRY,
    analyze,
)
from tradeflow.agent.response import build_response
from tradeflow.runtime.provenance import fingerprint_knowledge

KST = timezone(timedelta(hours=9))
AS_OF = date(2026, 7, 28)
NOW = datetime(2026, 7, 28, 12, tzinfo=KST)
SNAPSHOTS = REPO_ROOT / "data" / "snapshots"

CASES = [
    {"direction": "수입", "amount": "60000", "expected_payment_date": "2026-08-25"},
    {"direction": "수출", "amount": "100000", "expected_payment_date": "2026-10-24"},
]


def _program():
    return intake(CASES, opening_balances={"USD": "20000"}, as_of=AS_OF).program


def _response():
    return build_response(
        analyze(_program(), snapshot_root=SNAPSHOTS, as_of=NOW)
    )


class ReplayTests(unittest.TestCase):
    def test_the_same_inputs_reproduce_the_same_answer(self) -> None:
        """§9.1's acceptance criterion, run as a test rather than described."""
        first = _response()
        second = _response()

        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )

    def test_the_recorded_fingerprint_is_stable_across_runs(self) -> None:
        self.assertEqual(
            _response()["calculation_versions"]["input_fingerprint"],
            _response()["calculation_versions"]["input_fingerprint"],
        )

    def test_every_snapshot_the_answer_depended_on_is_recorded(self) -> None:
        """Both snapshots, not just the market one.

        The knowledge-source verification decides whether the rules may judge
        at all, so an answer that omits it cannot be replayed: the same market
        data with a different verification produces different decisions.
        """
        versions = _response()["calculation_versions"]

        recorded = {item["source_id"] for item in versions["snapshots"]}
        self.assertIn("ECOS_USD_KRW", recorded)
        self.assertIn("KNOWLEDGE_SOURCES", recorded)

    def test_the_rules_that_decided_are_identified_by_content(self) -> None:
        versions = _response()["calculation_versions"]

        packs = {
            item["path"]
            for item in versions["knowledge_files"]
            if item["role"] == "rulepack"
        }
        self.assertEqual(
            {
                "knowledge/rulepacks/fx_compliance_mvp.json",
                "knowledge/rulepacks/ksure_mvp_candidates.json",
            },
            packs,
        )
        for item in versions["knowledge_files"]:
            self.assertTrue(item["content_hash"].startswith("sha256:"))


class FingerprintSensitivityTests(unittest.TestCase):
    """What the version block must notice.

    The defect this replaces recorded `DecisionPacket.schema_version` as the
    rule version. That is a hardcoded constant, so an edited threshold produced
    a different answer under an identical version string.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        shutil.copytree(REPO_ROOT / "knowledge", self.root / "knowledge")

    def _fingerprint(self) -> tuple:
        return fingerprint_knowledge(
            repo_root=self.root,
            source_registry=self.root / "knowledge" / "source_registry.json",
            rulepacks=tuple(
                self.root / "knowledge" / "rulepacks" / pack.name
                for pack in RULEPACKS
            ),
            fact_catalog=self.root / "knowledge" / "fact_catalog.json",
        )

    def test_an_edited_rule_changes_the_recorded_version(self) -> None:
        before = self._fingerprint()

        pack = self.root / "knowledge" / "rulepacks" / "fx_compliance_mvp.json"
        data = json.loads(pack.read_text(encoding="utf-8"))
        data["rules"][0]["title"] = data["rules"][0]["title"] + " (개정)"
        pack.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

        self.assertNotEqual(before, self._fingerprint())

    def test_an_edited_source_registry_changes_the_recorded_version(self) -> None:
        """Source effective dates decide whether a rule may be applied."""
        before = self._fingerprint()

        registry = self.root / "knowledge" / "source_registry.json"
        data = json.loads(registry.read_text(encoding="utf-8"))
        data["sources"][0]["effective_to"] = "2030-12-31"
        registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        self.assertNotEqual(before, self._fingerprint())

    def test_an_edited_document_catalog_changes_the_recorded_version(self) -> None:
        """Catalogs are reached by path from inside a rulepack, not by name."""
        catalogs = sorted(
            (self.root / "knowledge" / "document_catalogs").glob("*.json")
        )
        self.assertTrue(catalogs, "expected at least one document catalog")

        before = self._fingerprint()
        recorded = {item.path for item in before}
        self.assertTrue(
            any(path.startswith("knowledge/document_catalogs/") for path in recorded),
            f"catalogs were not fingerprinted: {sorted(recorded)}",
        )

        data = json.loads(catalogs[0].read_text(encoding="utf-8"))
        data["_probe"] = "changed"
        catalogs[0].write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

        self.assertNotEqual(before, self._fingerprint())

    def test_renaming_the_repository_does_not_change_the_version(self) -> None:
        """A checkout under a different directory is the same rule set.

        Absolute paths would make CI and a developer machine look like they ran
        different rules, which would make the fingerprint useless for the one
        comparison it exists for.
        """
        first = self._fingerprint()

        moved = self.root.parent / (self.root.name + "-moved")
        shutil.copytree(self.root, moved)
        self.addCleanup(shutil.rmtree, moved, True)

        second = fingerprint_knowledge(
            repo_root=moved,
            source_registry=moved / "knowledge" / "source_registry.json",
            rulepacks=tuple(
                moved / "knowledge" / "rulepacks" / pack.name for pack in RULEPACKS
            ),
            fact_catalog=moved / "knowledge" / "fact_catalog.json",
        )

        self.assertEqual(first, second)


class InjectedPipelineTests(unittest.TestCase):
    def test_an_injected_pipeline_records_no_rule_files(self) -> None:
        """A pipeline built elsewhere was built from files we never read.

        Reporting the repository's own fingerprints would attribute the answer
        to rules that did not produce it — worse than recording nothing.
        """
        from tradeflow.knowledge.facts import FactAssembler, FactCatalog
        from tradeflow.knowledge.repository import KnowledgeRepository
        from tradeflow.runtime.pipeline import TradeFlowPipeline

        injected = TradeFlowPipeline(
            KnowledgeRepository.from_json_files(SOURCE_REGISTRY, RULEPACKS),
            fact_assembler=FactAssembler(FactCatalog.from_json(FACT_CATALOG)),
        )

        analysis = analyze(
            _program(),
            snapshot_root=SNAPSHOTS,
            knowledge_pipeline=injected,
            as_of=NOW,
        )

        self.assertEqual((), analysis.versions.knowledge_files)
        # The snapshots it really did read are still recorded.
        self.assertTrue(analysis.versions.snapshots)


if __name__ == "__main__":
    unittest.main()
