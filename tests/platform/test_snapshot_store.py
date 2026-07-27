import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from tradeflow.domain.snapshot_file import (
    SnapshotIntegrityError,
    content_hash,
    read_snapshot,
    snapshot_path,
)
from tradeflow.integration.snapshot_store import (
    SnapshotConflictError,
    build_envelope,
    write_snapshot,
)


KST = timezone(timedelta(hours=9))
OBSERVED = datetime(2026, 7, 26, 0, 0, tzinfo=KST)
RETRIEVED = datetime(2026, 7, 26, 9, 12, 31, tzinfo=KST)
PAYLOAD = {"rows": [{"date": "20260724", "rate": "1385.2"}]}


def _envelope(payload=PAYLOAD, version="2026-07-26"):
    return build_envelope(
        source_id="ECOS_USD_KRW",
        version=version,
        observed_at=OBSERVED,
        retrieved_at=RETRIEVED,
        payload=payload,
    )


class ContentHashTests(unittest.TestCase):
    def test_key_order_does_not_change_the_hash(self) -> None:
        self.assertEqual(
            content_hash({"a": 1, "b": 2}),
            content_hash({"b": 2, "a": 1}),
        )

    def test_different_payloads_hash_differently(self) -> None:
        self.assertNotEqual(
            content_hash({"rate": "1385.2"}),
            content_hash({"rate": "1385.3"}),
        )

    def test_hash_carries_its_algorithm(self) -> None:
        self.assertTrue(content_hash(PAYLOAD).startswith("sha256:"))


class EnvelopeTests(unittest.TestCase):
    def test_envelope_records_both_moments_with_offsets(self) -> None:
        envelope = _envelope()

        self.assertEqual("2026-07-26T00:00:00+09:00", envelope["observed_at"])
        self.assertEqual("2026-07-26T09:12:31+09:00", envelope["retrieved_at"])

    def test_payload_is_stored_unchanged(self) -> None:
        self.assertEqual(PAYLOAD, _envelope()["payload"])

    def test_naive_timestamp_is_rejected_before_reaching_disk(self) -> None:
        with self.assertRaises(ValueError):
            build_envelope(
                source_id="ECOS_USD_KRW",
                version="2026-07-26",
                observed_at=datetime(2026, 7, 26, 0, 0),
                retrieved_at=RETRIEVED,
                payload=PAYLOAD,
            )

    def test_future_observation_is_rejected_before_reaching_disk(self) -> None:
        with self.assertRaisesRegex(ValueError, "later than"):
            build_envelope(
                source_id="ECOS_USD_KRW",
                version="2026-07-27",
                observed_at=RETRIEVED + timedelta(seconds=1),
                retrieved_at=RETRIEVED,
                payload=PAYLOAD,
            )

    def test_path_traversal_in_identifiers_is_rejected(self) -> None:
        for source_id, version in (
            ("../escape", "2026-07-26"),
            ("ECOS_USD_KRW", "../escape"),
            ("ECOS/USD", "2026-07-26"),
        ):
            with self.subTest(source_id=source_id, version=version):
                with self.assertRaises(ValueError):
                    build_envelope(
                        source_id=source_id,
                        version=version,
                        observed_at=OBSERVED,
                        retrieved_at=RETRIEVED,
                        payload=PAYLOAD,
                    )


class WriteSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_snapshot_lands_at_the_documented_path(self) -> None:
        path = write_snapshot(self.root, _envelope())

        self.assertEqual(
            snapshot_path(self.root, "ECOS_USD_KRW", "2026-07-26"), path
        )
        self.assertTrue(path.exists())

    def test_recollecting_identical_content_is_a_no_op(self) -> None:
        first = write_snapshot(self.root, _envelope())
        before = first.read_text(encoding="utf-8")

        second = write_snapshot(self.root, _envelope())

        self.assertEqual(first, second)
        self.assertEqual(before, second.read_text(encoding="utf-8"))

    def test_recollecting_different_content_is_refused(self) -> None:
        write_snapshot(self.root, _envelope())

        with self.assertRaises(SnapshotConflictError) as caught:
            write_snapshot(self.root, _envelope(payload={"rows": []}))

        self.assertIn("2026-07-26", str(caught.exception))

    def test_refused_write_leaves_the_original_intact(self) -> None:
        path = write_snapshot(self.root, _envelope())

        with self.assertRaises(SnapshotConflictError):
            write_snapshot(self.root, _envelope(payload={"rows": []}))

        _, payload = read_snapshot(path)
        self.assertEqual(PAYLOAD, payload)

    def test_no_temporary_file_is_left_behind(self) -> None:
        write_snapshot(self.root, _envelope())

        self.assertEqual([], list(self.root.rglob("*.tmp")))


class ReadSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_round_trip_preserves_reference_and_payload(self) -> None:
        path = write_snapshot(self.root, _envelope())

        ref, payload = read_snapshot(path)

        self.assertEqual("ECOS_USD_KRW", ref.source_id)
        self.assertEqual("2026-07-26", ref.version)
        self.assertEqual(OBSERVED, ref.observed_at)
        self.assertEqual(RETRIEVED, ref.retrieved_at)
        self.assertEqual(content_hash(PAYLOAD), ref.content_hash)
        self.assertEqual(PAYLOAD, payload)

    def test_observed_and_retrieved_stay_distinct_across_the_round_trip(self) -> None:
        ref, _ = read_snapshot(write_snapshot(self.root, _envelope()))

        self.assertNotEqual(ref.observed_at, ref.retrieved_at)

    def test_altered_payload_is_detected(self) -> None:
        path = write_snapshot(self.root, _envelope())
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["rows"][0]["rate"] = "9999.9"
        path.write_text(json.dumps(envelope), encoding="utf-8")

        with self.assertRaises(SnapshotIntegrityError):
            read_snapshot(path)

    def test_naive_timestamp_in_a_stored_file_is_rejected(self) -> None:
        path = write_snapshot(self.root, _envelope())
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["observed_at"] = "2026-07-26T00:00:00"
        path.write_text(json.dumps(envelope), encoding="utf-8")

        with self.assertRaises(ValueError):
            read_snapshot(path)

    def test_path_must_match_envelope_identity(self) -> None:
        path = write_snapshot(self.root, _envelope())
        wrong_parent = self.root / "OTHER_SOURCE"
        wrong_parent.mkdir()
        moved = wrong_parent / path.name
        path.replace(moved)

        with self.assertRaisesRegex(SnapshotIntegrityError, "path identity"):
            read_snapshot(moved)

    def test_utc_snapshot_round_trips(self) -> None:
        envelope = build_envelope(
            source_id="ECOS_USD_KRW",
            version="2026-07-27",
            observed_at=datetime(2026, 7, 27, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 27, 1, tzinfo=UTC),
            payload=PAYLOAD,
        )

        ref, _ = read_snapshot(write_snapshot(self.root, envelope))

        self.assertEqual(datetime(2026, 7, 27, tzinfo=UTC), ref.observed_at)


if __name__ == "__main__":
    unittest.main()
