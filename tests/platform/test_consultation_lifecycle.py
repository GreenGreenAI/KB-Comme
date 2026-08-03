import sqlite3
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from tradeflow.contracts.consultation_packet import build_consultation_packet
from tradeflow.runtime.accounts import AccountStore


class ConsultationLifecycleTests(unittest.TestCase):
    def test_passport_exposes_document_inventory_without_raw_content(self) -> None:
        packet = build_consultation_packet(
            run_id="RUN-1",
            analysis_created_at="2026-08-02T00:00:00+00:00",
            consented_at="2026-08-02T00:01:00+00:00",
            result={"packet_id": "PACKET-1"},
            requested_by="owner@example.com",
            uploaded_documents=({
                "document_id": "DOC-1",
                "filename": "invoice.pdf",
                "content_hash": "sha256:test",
                "confirmed_fields": ["amount"],
            },),
        )

        self.assertEqual("1.1", packet["schema_version"])
        self.assertEqual(1, packet["consultation_readiness"]["uploaded_document_count"])
        self.assertEqual("DOC-1", packet["document_inventory"][0]["document_id"])
        self.assertFalse(packet["privacy"]["raw_document_content_included"])
        self.assertNotIn(
            "documents.uploaded_inventory",
            {
                item["field"]
                for item in packet["consultation_readiness"]["missing_or_unverified"]
            },
        )

    def test_lifecycle_is_append_only_tenant_scoped_and_user_recorded(self) -> None:
        with TemporaryDirectory() as directory:
            store = AccountStore(Path(directory) / "accounts.db")
            owner = store.create("owner@example.com", "pw", company_name="한빛")
            outsider = store.create("other@example.com", "pw", company_name="다른 회사")
            run_id = store.save_analysis(owner, {"packet_id": "PACKET-1"})
            start = datetime(2026, 8, 2, tzinfo=UTC)

            store.record_consultation_event(
                owner,
                run_id,
                handoff_id="HANDOFF-1",
                status="ready_for_manual_handoff",
                now=start,
            )
            store.record_consultation_event(
                owner,
                run_id,
                handoff_id="HANDOFF-1",
                status="shared_manually",
                now=start + timedelta(seconds=1),
            )
            consultation = store.record_consultation_event(
                owner,
                run_id,
                handoff_id="HANDOFF-1",
                status="consultation_in_progress",
                now=start + timedelta(seconds=2),
            )

            self.assertEqual("consultation_in_progress", consultation["status"])
            self.assertEqual(3, len(consultation["history"]))
            self.assertEqual(
                "user_recorded_not_bank_verified",
                consultation["verification"],
            )
            self.assertIsNone(store.read_consultation(outsider, run_id))
            with self.assertRaises(sqlite3.IntegrityError):
                with closing(sqlite3.connect(store.path)) as db, db:
                    db.execute(
                        "UPDATE consultation_events SET status = 'outcome_recorded'"
                    )

    def test_invalid_or_unexplained_transitions_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            store = AccountStore(Path(directory) / "accounts.db")
            account = store.create("owner@example.com", "pw", company_name="한빛")
            run_id = store.save_analysis(account, {"packet_id": "PACKET-1"})
            store.record_consultation_event(
                account,
                run_id,
                handoff_id="HANDOFF-1",
                status="ready_for_manual_handoff",
            )
            with self.assertRaisesRegex(ValueError, "cannot transition"):
                store.record_consultation_event(
                    account,
                    run_id,
                    handoff_id="HANDOFF-1",
                    status="outcome_recorded",
                    note="승인",
                )


if __name__ == "__main__":
    unittest.main()
