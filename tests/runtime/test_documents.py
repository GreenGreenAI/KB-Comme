import base64
import tempfile
import unittest
import io
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tradeflow.runtime.documents import (
    ClamAvScanner,
    DocumentValidationError,
    TradeDocumentStore,
    decode_upload,
    inspect_and_extract,
)


INVOICE = """Commercial Invoice
Invoice No: INV-2026-001
Invoice Date: 2026-07-20
Seller: Hanbit Precision
Buyer: Green Import LLC
Amount: USD 100,000
Shipment Date: 2026-08-01
Description of Goods: Precision gears
"""


class DocumentInspectionTests(unittest.TestCase):
    def test_invoice_is_classified_and_fields_keep_source_location(self) -> None:
        result = inspect_and_extract(
            filename="invoice.txt",
            content_type="text/plain",
            content=INVOICE.encode(),
        )
        fields = {item["field_name"]: item for item in result["fields"]}

        self.assertEqual("commercial_invoice", result["document_type"])
        self.assertEqual("100000", fields["amount"]["normalized_value"])
        self.assertEqual("USD", fields["currency"]["normalized_value"])
        self.assertGreater(fields["amount"]["location"]["line"], 0)
        self.assertFalse(fields["amount"]["confirmed"])

    def test_unsafe_name_type_and_active_content_fail_closed(self) -> None:
        cases = (
            ("../invoice.txt", "text/plain", INVOICE.encode()),
            ("invoice.pdf", "text/plain", INVOICE.encode()),
            ("invoice.txt", "text/plain", b"<script>alert(1)</script>"),
        )
        for filename, content_type, content in cases:
            with self.subTest(filename=filename):
                with self.assertRaises(DocumentValidationError):
                    inspect_and_extract(
                        filename=filename,
                        content_type=content_type,
                        content=content,
                    )

    def test_base64_decoder_rejects_invalid_and_oversize_input(self) -> None:
        with self.assertRaises(DocumentValidationError):
            decode_upload("not base64")
        encoded = base64.b64encode(INVOICE.encode()).decode()
        self.assertEqual(INVOICE.encode(), decode_upload(encoded))

    def test_image_ocr_output_enters_the_same_reviewable_extraction_contract(self) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), "white").save(buffer, format="PNG")
        result = inspect_and_extract(
            filename="invoice.png",
            content_type="image/png",
            content=buffer.getvalue(),
            ocr=lambda _image: INVOICE,
        )

        self.assertEqual("extracted", result["extraction_state"])
        self.assertEqual("commercial_invoice", result["document_type"])
        self.assertTrue(
            any(item["field_name"] == "amount" for item in result["fields"])
        )

    def test_malware_scanner_fails_closed_on_detection_and_scanner_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "clamscan"
            executable.touch()
            scanner = ClamAvScanner(executable)
            for return_code, reason in (
                (1, "rejected"),
                (2, "could not verify"),
            ):
                with self.subTest(return_code=return_code):
                    with patch(
                        "tradeflow.runtime.documents.subprocess.run",
                        return_value=subprocess.CompletedProcess(
                            args=[],
                            returncode=return_code,
                            stdout="",
                            stderr="",
                        ),
                    ):
                        with self.assertRaisesRegex(DocumentValidationError, reason):
                            scanner.scan(INVOICE.encode(), "invoice.txt")


class TradeDocumentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.store = TradeDocumentStore(
            root / "documents.db",
            root / "blobs",
            b"k" * 32,
        )

    def save(self, account: str = "COMPANY-A", text: str = INVOICE):
        return self.store.save(
            account_id=account,
            case_id="EXPORT-001",
            filename="invoice.txt",
            content_type="text/plain",
            content=text.encode(),
        )

    def test_original_is_encrypted_and_reads_are_tenant_scoped(self) -> None:
        document = self.save()
        blobs = list((Path(self.directory.name) / "blobs").glob("*.bin"))

        self.assertEqual(1, len(blobs))
        self.assertNotIn(b"Commercial Invoice", blobs[0].read_bytes())
        self.assertIsNone(self.store.read("COMPANY-B", document["document_id"]))
        self.assertEqual(
            document["document_id"],
            self.store.read("COMPANY-A", document["document_id"])["document_id"],
        )

    def test_confirmation_preserves_extracted_value_and_records_actor(self) -> None:
        document = self.save()
        confirmed = self.store.confirm(
            "COMPANY-A",
            document["document_id"],
            {"amount": "99,000"},
            confirmed_by="ACCOUNT-1",
        )
        amount = next(
            item
            for item in confirmed["extraction"]["fields"]
            if item["field_name"] == "amount"
        )

        self.assertEqual("100000", amount["normalized_value"])
        self.assertEqual("99000", amount["confirmed_value"])
        self.assertEqual("ACCOUNT-1", amount["confirmed_by"])

    def test_document_and_trade_mismatches_require_review(self) -> None:
        first = self.save()
        self.store.confirm(
            "COMPANY-A",
            first["document_id"],
            {"amount": "99000"},
            confirmed_by="ACCOUNT-1",
        )
        packing = INVOICE.replace("Commercial Invoice", "Packing List").replace(
            "Amount: USD 100,000",
            "Amount: USD 98,000",
        )
        self.store.save(
            account_id="COMPANY-A",
            case_id="EXPORT-001",
            filename="packing.txt",
            content_type="text/plain",
            content=packing.encode(),
        )

        result = self.store.check_case(
            "COMPANY-A",
            "EXPORT-001",
            {"amount": "100000", "currency": "USD"},
        )

        self.assertTrue(result["review_required"])
        self.assertIn(
            "cross_document_mismatch",
            {item["kind"] for item in result["findings"]},
        )
        self.assertIn(
            "trade_document_mismatch",
            {item["kind"] for item in result["findings"]},
        )

    def test_same_content_is_idempotent_within_one_case(self) -> None:
        first = self.save()
        second = self.save()
        self.assertEqual(first["document_id"], second["document_id"])


if __name__ == "__main__":
    unittest.main()
