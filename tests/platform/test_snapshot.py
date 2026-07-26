import unittest
from datetime import UTC, datetime, timedelta, timezone

from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import FreshnessPolicy, SnapshotRef


DAILY = FreshnessPolicy(max_observation_age=timedelta(days=1))
KST = timezone(timedelta(hours=9))


def _ref(
    observed_at: datetime,
    retrieved_at: datetime | None = None,
) -> SnapshotRef:
    return SnapshotRef(
        "ECOS_USD_KRW",
        "2026-07-26",
        observed_at,
        retrieved_at if retrieved_at is not None else observed_at,
        "sha256:test",
    )


class SnapshotRefTests(unittest.TestCase):
    def test_version_is_required_for_reproducibility(self) -> None:
        moment = datetime(2026, 7, 26, tzinfo=UTC)
        with self.assertRaises(ValueError):
            SnapshotRef("ECOS_USD_KRW", "", moment, moment, "sha256:test")

    def test_content_hash_is_required_for_reproducibility(self) -> None:
        moment = datetime(2026, 7, 26, tzinfo=UTC)
        with self.assertRaises(ValueError):
            SnapshotRef("ECOS_USD_KRW", "2026-07-26", moment, moment, "")

    def test_naive_timestamp_is_rejected_not_assumed_utc(self) -> None:
        naive = datetime(2026, 7, 26, 9, 0)
        aware = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)

        with self.assertRaises(ValueError):
            SnapshotRef("ECOS_USD_KRW", "2026-07-26", naive, aware, "sha256:test")
        with self.assertRaises(ValueError):
            SnapshotRef("ECOS_USD_KRW", "2026-07-26", aware, naive, "sha256:test")

    def test_offsets_other_than_utc_are_accepted(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 18, 0, tzinfo=KST))
        self.assertEqual(
            Freshness.FRESH,
            DAILY.evaluate(ref, datetime(2026, 7, 26, 12, 0, tzinfo=UTC)),
        )


class FreshnessPolicyTests(unittest.TestCase):
    def test_recent_observation_is_fresh(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0, tzinfo=UTC))
        self.assertEqual(
            Freshness.FRESH,
            DAILY.evaluate(ref, datetime(2026, 7, 27, 8, 0, tzinfo=UTC)),
        )

    def test_observation_past_sla_is_stale(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0, tzinfo=UTC))
        as_of = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

        self.assertEqual(Freshness.STALE, DAILY.evaluate(ref, as_of))
        self.assertFalse(DAILY.is_usable(ref, as_of))

    def test_old_data_fetched_today_is_stale(self) -> None:
        """A fresh fetch of a stale reading is still a stale reading."""
        ref = _ref(
            observed_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 27, 9, 0, tzinfo=UTC),
        )

        self.assertEqual(
            Freshness.STALE,
            DAILY.evaluate(ref, datetime(2026, 7, 27, 9, 30, tzinfo=UTC)),
        )

    def test_retrieval_age_is_checked_when_the_policy_sets_one(self) -> None:
        policy = FreshnessPolicy(
            max_observation_age=timedelta(days=30),
            max_retrieval_age=timedelta(days=1),
        )
        ref = _ref(
            observed_at=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
            retrieved_at=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
        )

        self.assertEqual(
            Freshness.STALE,
            policy.evaluate(ref, datetime(2026, 7, 30, 9, 0, tzinfo=UTC)),
        )

    def test_future_observation_is_stale_not_guessed(self) -> None:
        ref = _ref(datetime(2026, 7, 30, 9, 0, tzinfo=UTC))
        self.assertEqual(
            Freshness.STALE,
            DAILY.evaluate(ref, datetime(2026, 7, 26, 9, 0, tzinfo=UTC)),
        )

    def test_naive_evaluation_instant_is_rejected(self) -> None:
        ref = _ref(datetime(2026, 7, 26, 9, 0, tzinfo=UTC))
        with self.assertRaises(ValueError):
            DAILY.evaluate(ref, datetime(2026, 7, 26, 18, 0))


if __name__ == "__main__":
    unittest.main()
