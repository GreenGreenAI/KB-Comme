import unittest
from datetime import UTC, datetime, timedelta

from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef


DAILY = FreshnessPolicy(max_age=timedelta(days=1))


def _ref(retrieved_at: datetime) -> SnapshotRef:
    return SnapshotRef("ECOS_USD_KRW", "2026-07-26", retrieved_at)


class SnapshotRefTests(unittest.TestCase):
    def test_version_is_required_for_reproducibility(self) -> None:
        with self.assertRaises(ValueError):
            SnapshotRef("ECOS_USD_KRW", "", datetime(2026, 7, 26, tzinfo=UTC))

    def test_naive_timestamp_is_read_as_utc(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0))
        self.assertEqual(UTC, ref.retrieved_at.tzinfo)


class FreshnessPolicyTests(unittest.TestCase):
    def test_snapshot_within_sla_is_fresh(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0, tzinfo=UTC))
        self.assertEqual(
            Freshness.FRESH,
            DAILY.evaluate(ref, datetime(2026, 7, 27, 8, 0, tzinfo=UTC)),
        )

    def test_snapshot_past_sla_is_stale(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0, tzinfo=UTC))
        self.assertEqual(
            Freshness.STALE,
            DAILY.evaluate(ref, datetime(2026, 7, 28, 9, 0, tzinfo=UTC)),
        )
        self.assertFalse(DAILY.is_usable(ref, datetime(2026, 7, 28, 9, 0, tzinfo=UTC)))

    def test_future_retrieval_is_stale_not_guessed(self) -> None:
        """A snapshot retrieved after the evaluation instant is a data error."""
        ref = _ref(datetime(2026, 7, 30, 9, 0, tzinfo=UTC))
        self.assertEqual(
            Freshness.STALE,
            DAILY.evaluate(ref, datetime(2026, 7, 26, 9, 0, tzinfo=UTC)),
        )

    def test_naive_and_aware_timestamps_compare(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0))
        self.assertEqual(
            Freshness.FRESH,
            DAILY.evaluate(ref, datetime(2026, 7, 26, 18, 0)),
        )


if __name__ == "__main__":
    unittest.main()
