"""Tests for the ECOS collector's pure parts.

The HTTP call itself is not covered here: CI runs without network or an API
key (ADR-0003). What is covered is everything that decides how a response
becomes a snapshot — which moment it describes, and where the key comes from.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tradeflow.integration.ecos import (
    API_KEY_ENV,
    EcosError,
    load_api_key,
    observed_at,
    observed_date,
)


KST = timezone(timedelta(hours=9))


def _payload(*times: str) -> dict:
    return {
        "list_total_count": len(times),
        "row": [
            {
                "STAT_CODE": "731Y001",
                "ITEM_CODE1": "0000001",
                "ITEM_NAME1": "원/미국달러(매매기준율)",
                "UNIT_NAME": "원",
                "TIME": time,
                "DATA_VALUE": "1469.4",
            }
            for time in times
        ],
    }


class ObservedMomentTests(unittest.TestCase):
    def test_latest_business_day_is_the_observed_date(self) -> None:
        payload = _payload("20260722", "20260724", "20260723")

        self.assertEqual("2026-07-24", observed_date(payload).isoformat())

    def test_observation_sits_at_the_start_of_the_day_in_kst(self) -> None:
        moment = observed_at(_payload("20260724"))

        self.assertEqual(datetime(2026, 7, 24, 0, 0, tzinfo=KST), moment)
        self.assertEqual(KST, moment.tzinfo)

    def test_empty_payload_is_refused(self) -> None:
        with self.assertRaises(EcosError):
            observed_date(_payload())


class ApiKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_environment_wins(self) -> None:
        with mock.patch.dict(os.environ, {API_KEY_ENV: "from-env"}):
            self.assertEqual("from-env", load_api_key(self.root))

    def test_env_file_is_found_by_walking_upward(self) -> None:
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        (self.root / ".env").write_text(
            f"OTHER=x\n{API_KEY_ENV}=from-file\n", encoding="utf-8"
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("from-file", load_api_key(nested))

    def test_quotes_are_stripped(self) -> None:
        (self.root / ".env").write_text(
            f'{API_KEY_ENV}="quoted"\n', encoding="utf-8"
        )

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("quoted", load_api_key(self.root))

    def test_missing_key_is_an_explicit_error(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(EcosError) as caught:
                load_api_key(self.root)

        self.assertIn(API_KEY_ENV, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
