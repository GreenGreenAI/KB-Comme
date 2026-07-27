import json
import tempfile
import unittest
from pathlib import Path

from tradeflow.domain.enums import DocumentRequirementKind, RuleType
from tradeflow.domain.models import DocumentOption, DocumentRequirementGroup
from tradeflow.knowledge.documents import ApplicationDocumentSet, DocumentCatalog
from tradeflow.knowledge.models import KnowledgeRule
from tradeflow.knowledge.repository import KnowledgeRepository


class DocumentCatalogContractTests(unittest.TestCase):
    def test_one_of_requires_multiple_options_and_a_selector(self) -> None:
        options = (
            DocumentOption("D1", "First"),
            DocumentOption("D2", "Second"),
        )
        with self.assertRaisesRegex(ValueError, "needs selector_field"):
            DocumentRequirementGroup(
                "R1", DocumentRequirementKind.ONE_OF, options
            )
        with self.assertRaisesRegex(ValueError, "needs two options"):
            DocumentRequirementGroup(
                "R1",
                DocumentRequirementKind.ONE_OF,
                options[:1],
                selector_field="trade.type",
            )

    def test_catalog_rejects_an_unknown_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(
                json.dumps({"schema_version": "9.9", "document_sets": []}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                DocumentCatalog.from_json(path)

    def test_rule_cannot_mix_inline_and_catalog_documents(self) -> None:
        requirement = DocumentRequirementGroup(
            "REQ",
            DocumentRequirementKind.REQUIRED,
            (DocumentOption("DOC", "Application"),),
        )
        document_set = ApplicationDocumentSet(
            "SET",
            "product",
            "application",
            "v1",
            ("SOURCE",),
            ("CLAIM",),
            (requirement,),
        )
        rule = KnowledgeRule(
            "RULE",
            "Rule",
            "topic",
            RuleType.PROCEDURE,
            (),
            ("SOURCE",),
            required_documents=("legacy",),
            candidate_outcome={"product_id": "product"},
            document_set_ids=("SET",),
        )
        with self.assertRaisesRegex(ValueError, "not both"):
            KnowledgeRepository((), (rule,), (document_set,))

    def test_document_set_rejects_duplicate_requirement_identity(self) -> None:
        requirement = DocumentRequirementGroup(
            "REQ",
            DocumentRequirementKind.REQUIRED,
            (DocumentOption("DOC", "Application"),),
        )
        with self.assertRaisesRegex(ValueError, "duplicate requirement_id"):
            ApplicationDocumentSet(
                "SET",
                "product",
                "application",
                "v1",
                ("SOURCE",),
                ("CLAIM",),
                (requirement, requirement),
            )


if __name__ == "__main__":
    unittest.main()
