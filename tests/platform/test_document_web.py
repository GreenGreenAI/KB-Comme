import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from tradeflow.runtime.accounts import AccountStore
from tradeflow.runtime.documents import TradeDocumentStore
from tradeflow.web.app import (
    DocumentCheckRequest,
    DocumentConfirmationRequest,
    DocumentUploadRequest,
    check_trade_documents,
    confirm_document_fields,
    document_extraction,
    list_trade_documents,
    upload_document,
)


INVOICE = b"""Commercial Invoice
Invoice No: INV-001
Amount: USD 100,000
Shipment Date: 2026-08-01
"""


class DocumentWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.accounts = AccountStore(root / "app.db")
        self.alpha = self.accounts.create(
            "alpha@example.com",
            "pw",
            company_name="Alpha",
            account_id="COMPANY-A",
        )
        self.beta = self.accounts.create(
            "beta@example.com",
            "pw",
            company_name="Beta",
            account_id="COMPANY-B",
        )
        self.alpha_token = self.accounts.open_session(self.alpha)
        self.beta_token = self.accounts.open_session(self.beta)
        self.documents = TradeDocumentStore(
            root / "app.db",
            root / "documents",
            b"d" * 32,
        )
        self.patches = (
            patch("tradeflow.web.app.accounts", self.accounts),
            patch("tradeflow.web.app.document_store", self.documents),
        )
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def upload(self) -> dict:
        return upload_document(
            "EXPORT-001",
            DocumentUploadRequest(
                filename="invoice.txt",
                content_type="text/plain",
                content_base64=base64.b64encode(INVOICE).decode(),
            ),
            session=self.alpha_token,
        )["document"]

    def test_upload_extraction_confirmation_and_check_flow(self) -> None:
        document = self.upload()
        read = document_extraction(
            document["document_id"],
            session=self.alpha_token,
        )["document"]
        listed = list_trade_documents(
            "EXPORT-001",
            session=self.alpha_token,
        )["documents"]
        confirmed = confirm_document_fields(
            document["document_id"],
            DocumentConfirmationRequest(fields={"amount": "100000"}),
            session=self.alpha_token,
        )["document"]
        checked = check_trade_documents(
            "EXPORT-001",
            DocumentCheckRequest(
                expected_fields={"amount": "99999", "currency": "USD"}
            ),
            session=self.alpha_token,
        )

        self.assertEqual("commercial_invoice", read["document_type"])
        self.assertEqual([document["document_id"]], [item["document_id"] for item in listed])
        self.assertTrue(
            next(
                item
                for item in confirmed["extraction"]["fields"]
                if item["field_name"] == "amount"
            )["confirmed"]
        )
        self.assertTrue(checked["review_required"])

    def test_cross_tenant_document_id_is_indistinguishable_from_missing(self) -> None:
        document = self.upload()
        with self.assertRaises(HTTPException) as context:
            document_extraction(
                document["document_id"],
                session=self.beta_token,
            )

        self.assertEqual(404, context.exception.status_code)

    def test_upload_requires_authentication(self) -> None:
        with self.assertRaises(HTTPException) as context:
            upload_document(
                "EXPORT-001",
                DocumentUploadRequest(
                    filename="invoice.txt",
                    content_type="text/plain",
                    content_base64=base64.b64encode(INVOICE).decode(),
                ),
            )

        self.assertEqual(401, context.exception.status_code)


if __name__ == "__main__":
    unittest.main()
