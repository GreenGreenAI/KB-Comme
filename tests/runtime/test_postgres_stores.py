import os
import secrets
import tempfile
import unittest
from pathlib import Path

import psycopg

from tradeflow.runtime.documents import PostgresTradeDocumentStore
from tradeflow.runtime.postgres_accounts import PostgresAccountStore


DATABASE_URL = os.environ.get("TRADEFLOW_TEST_POSTGRES_URL")


@unittest.skipUnless(DATABASE_URL, "TRADEFLOW_TEST_POSTGRES_URL is not configured")
class PostgresStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.accounts = PostgresAccountStore(DATABASE_URL)

    def setUp(self) -> None:
        suffix = secrets.token_hex(6)
        self.organization = f"ORG-{suffix}"
        self.admin = self.accounts.create(
            f"admin-{suffix}@example.com",
            "strong-password",
            company_name="Postgres Tenant",
            account_id=f"ACCOUNT-{suffix}-A",
            organization_id=self.organization,
            role="company_admin",
        )
        self.user = self.accounts.create(
            f"user-{suffix}@example.com",
            "strong-password",
            company_name="Postgres Tenant",
            account_id=f"ACCOUNT-{suffix}-U",
            organization_id=self.organization,
            role="company_user",
        )

    def test_account_session_tenant_history_and_audit_contract(self) -> None:
        token = self.accounts.open_session(self.user)
        self.assertEqual(self.user.account_id, self.accounts.read_session(token).account_id)
        run_id = self.accounts.save_analysis(
            self.user,
            {
                "packet_id": "packet:postgres",
                "company_profile": {"company_name": "Postgres Tenant"},
                "trade_timeline": [],
            },
        )
        self.assertEqual(
            run_id,
            self.accounts.read_analysis(self.admin, run_id)["run_id"],
        )
        first = self.accounts.append_audit(
            self.user,
            action="analysis.create",
            target_type="analysis",
            target_id=run_id,
        )
        second = self.accounts.append_audit(
            self.admin,
            action="analysis.read",
            target_type="analysis",
            target_id=run_id,
        )

        self.assertEqual(first["event_hash"], second["previous_hash"])
        self.assertTrue(self.accounts.verify_audit_chain(self.organization))
        with self.assertRaises(psycopg.Error):
            with psycopg.connect(DATABASE_URL) as db:
                db.execute(
                    "UPDATE audit_events SET action = 'tampered'"
                    " WHERE event_id = %s",
                    (first["event_id"],),
                )

    def test_document_metadata_and_encrypted_blob_use_production_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            documents = PostgresTradeDocumentStore(
                DATABASE_URL,
                Path(directory),
                b"p" * 32,
            )
            uploaded = documents.save(
                account_id=self.organization,
                case_id="EXPORT-001",
                filename="invoice.txt",
                content_type="text/plain",
                content=(
                    b"Commercial Invoice\nInvoice No: INV-PG\n"
                    b"Amount: USD 100000\n"
                ),
            )
            blobs = list(Path(directory).glob("*.bin"))

            self.assertEqual("commercial_invoice", uploaded["document_type"])
            self.assertNotIn(b"Commercial Invoice", blobs[0].read_bytes())
            self.assertIsNone(
                documents.read("ANOTHER-ORG", uploaded["document_id"])
            )


if __name__ == "__main__":
    unittest.main()
