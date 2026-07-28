"""Turning recorded source verifications into rule-engine freshness.

The rule engine checks a source's status before it evaluates any condition, so
what this module returns decides whether a rule can be judged at all. The tests
below defend the distinction that makes the result honest: a source we checked
and found changed is not the same as a source we never reached.
"""

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from tradeflow.domain.enums import Freshness
from tradeflow.domain.snapshot import FreshnessPolicy
from tradeflow.domain.snapshot_file import content_hash
from tradeflow.integration.snapshot_store import build_envelope, write_snapshot
from tradeflow.tools.source_freshness import (
    SOURCE_ID,
    VerificationUnavailableError,
    load_source_freshness,
)
from scripts.check_sources import source_verification_version

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def _payload(results):
    return {"schema_version": "1.0", "results": list(results)}


def _result(source_id: str, status: str, **extra):
    base = {
        "source_id": source_id,
        "checked_at": NOW.isoformat(),
        "status": status,
        "http_status": 200,
        "final_url": f"https://example.invalid/{source_id}",
        "content_type": "text/html",
        "content_length": 100,
        "response_sha256": "sha256:" + "0" * 64,
        "missing_markers": [],
        "storage_policy": "metadata_and_fingerprint_only",
        "error": None,
    }
    base.update(extra)
    return base


def _write(root: Path, results, *, observed: datetime = NOW) -> None:
    payload = _payload(results)
    directory = root / SOURCE_ID
    directory.mkdir(parents=True, exist_ok=True)
    version = source_verification_version(observed)
    (directory / f"{version}.json").write_text(
        json.dumps(
            {
                "source_id": SOURCE_ID,
                "version": version,
                "observed_at": observed.isoformat(),
                "retrieved_at": observed.isoformat(),
                "content_hash": content_hash(payload),
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )


class SourceFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_a_verified_source_is_fresh(self) -> None:
        _write(self.root, [_result("FX_ACT", "verified")])

        self.assertEqual(
            {"FX_ACT": Freshness.FRESH},
            load_source_freshness(self.root, as_of=NOW),
        )

    def test_a_changed_source_is_stale(self) -> None:
        """Markers gone means the enacted text moved; that is an observation."""
        _write(
            self.root,
            [
                _result(
                    "FX_ACT",
                    "changed_or_unavailable",
                    missing_markers=["[시행 2026. 1. 2.]"],
                )
            ],
        )

        self.assertEqual(
            {"FX_ACT": Freshness.STALE},
            load_source_freshness(self.root, as_of=NOW),
        )

    def test_an_unreachable_source_is_not_reported_as_stale(self) -> None:
        """We never saw the page, so we cannot claim it changed.

        Leaving it out of the mapping makes the engine fall back to
        FRESHNESS_UNKNOWN. Both outcomes stop automatic judgement, but only one
        of them is a statement about the source itself.
        """
        _write(
            self.root,
            [
                _result("FX_ACT", "verified"),
                _result(
                    "KOREAEXIM",
                    "unreachable",
                    http_status=0,
                    error="URLError: CERTIFICATE_VERIFY_FAILED",
                ),
            ],
        )

        freshness = load_source_freshness(self.root, as_of=NOW)

        self.assertEqual({"FX_ACT": Freshness.FRESH}, freshness)
        self.assertNotIn("KOREAEXIM", freshness)

    def test_one_unreachable_source_does_not_hide_the_others(self) -> None:
        """The reason check_all isolates failures, stated as a test."""
        _write(
            self.root,
            [
                _result("A", "verified"),
                _result("B", "unreachable", http_status=0, error="URLError"),
                _result("C", "verified"),
            ],
        )

        freshness = load_source_freshness(self.root, as_of=NOW)

        self.assertEqual(
            {"A": Freshness.FRESH, "C": Freshness.FRESH}, freshness
        )

    def test_an_old_verification_is_refused_rather_than_trusted(self) -> None:
        """Yesterday's check says nothing about a statute amended since."""
        _write(self.root, [_result("FX_ACT", "verified")])

        with self.assertRaises(VerificationUnavailableError):
            load_source_freshness(
                self.root, as_of=NOW + timedelta(days=45)
            )

    def test_a_missing_snapshot_raises_instead_of_defaulting_to_fresh(self) -> None:
        with self.assertRaises(VerificationUnavailableError):
            load_source_freshness(self.root, as_of=NOW)

    def test_an_unknown_status_is_left_unresolved(self) -> None:
        """A status a later collector adds must not silently read as verified."""
        _write(self.root, [_result("FX_ACT", "rate_limited")])

        self.assertEqual({}, load_source_freshness(self.root, as_of=NOW))

    def test_the_newest_verification_wins(self) -> None:
        _write(
            self.root,
            [_result("FX_ACT", "verified")],
            observed=NOW - timedelta(days=2),
        )
        _write(
            self.root,
            [_result("FX_ACT", "changed_or_unavailable")],
            observed=NOW,
        )

        self.assertEqual(
            {"FX_ACT": Freshness.STALE},
            load_source_freshness(self.root, as_of=NOW),
        )

    def test_a_second_run_on_the_same_day_is_preserved_and_becomes_latest(
        self,
    ) -> None:
        first_at = NOW.replace(hour=9, minute=0)
        second_at = NOW.replace(hour=9, minute=5)
        first_payload = _payload([_result("FX_ACT", "verified")])
        second_payload = _payload(
            [_result("FX_ACT", "changed_or_unavailable")]
        )

        first = write_snapshot(
            self.root,
            build_envelope(
                source_id=SOURCE_ID,
                version=source_verification_version(first_at),
                observed_at=first_at,
                retrieved_at=first_at,
                payload=first_payload,
            ),
        )
        second = write_snapshot(
            self.root,
            build_envelope(
                source_id=SOURCE_ID,
                version=source_verification_version(second_at),
                observed_at=second_at,
                retrieved_at=second_at,
                payload=second_payload,
            ),
        )

        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(
            {"FX_ACT": Freshness.STALE},
            load_source_freshness(self.root, as_of=NOW),
        )

    def test_the_policy_is_configurable_for_a_stricter_caller(self) -> None:
        _write(self.root, [_result("FX_ACT", "verified")])

        with self.assertRaises(VerificationUnavailableError):
            load_source_freshness(
                self.root,
                as_of=NOW + timedelta(hours=2),
                policy=FreshnessPolicy(max_observation_age=timedelta(hours=1)),
            )


if __name__ == "__main__":
    unittest.main()
