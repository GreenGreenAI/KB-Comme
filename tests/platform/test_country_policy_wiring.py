import json
import shutil
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tradeflow.agent.intake import intake
from tradeflow.agent.orchestrator import (
    COUNTRY_POLICY_SOURCE,
    _country_policy_assertions,
)
from tradeflow.domain.snapshot_file import content_hash

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_SNAPSHOTS = REPO_ROOT / "data" / "snapshots"
AS_OF = date(2026, 7, 28)


def _catalog() -> dict:
    """A country catalog in the shape §5.4's parser accepts.

    Brazil is listed as conditional so the wiring can be proved without waiting
    on the real snapshot. The values are a fixture and say so — the live path
    reads whatever K-SURE published, and there is no defensible default to fall
    back on when it is absent.
    """
    codes = ("BR", "US", "SY")
    return {
        "schema_version": "1.0",
        "directory": {
            "getNationLst": [
                {"stdInfrmCtryCd": code, "trgtpsnNm": f"Country {code}"}
                for code in codes
            ]
        },
        "policy_filters": {
            "normal": {"selectFilterLst": [{"ggCode": "US", "trgtpsnNm": "Country US"}]},
            "conditional": {
                "selectFilterLst": [{"ggCode": "BR", "trgtpsnNm": "Country BR"}]
            },
            "restricted": {
                "selectFilterLst": [{"ggCode": "SY", "trgtpsnNm": "Country SY"}]
            },
            "deep_watch": {"selectFilterLst": []},
        },
    }


def _write_snapshot(root: Path, payload: dict) -> None:
    folder = root / COUNTRY_POLICY_SOURCE
    folder.mkdir(parents=True, exist_ok=True)
    version = "2026-07-27"
    moment = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc).isoformat()
    (folder / f"{version}.json").write_text(
        json.dumps(
            {
                "source_id": COUNTRY_POLICY_SOURCE,
                "version": version,
                "observed_at": moment,
                "retrieved_at": moment,
                "content_hash": content_hash(payload),
                "payload": payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _program(country: str | None):
    case = {
        "direction": "수출",
        "amount": "120000",
        "expected_payment_date": "2026-10-30",
    }
    if country:
        case["country"] = country
    return intake([case], as_of=AS_OF).program


class CountryPolicyWiringTests(unittest.TestCase):
    """`bind_country_policy` had tests and no caller.

    It was written, verified and never reached from the pipeline, so a trade
    that named Brazil was analysed as a trade that named nowhere. These pin the
    wiring, and the fixture stands in for a snapshot the repository does not
    have yet.
    """

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_a_listed_country_becomes_a_fact_with_its_evidence(self) -> None:
        _write_snapshot(self.root, _catalog())
        program = _program("BR")

        assertions, evidence = _country_policy_assertions(program, self.root)

        stated = assertions[program.cases[0].case_id]
        self.assertEqual(len(stated), 1)
        self.assertEqual(stated[0].field, "counterparty.country_restricted")
        self.assertIs(stated[0].value, False)  # conditional, not restricted
        self.assertEqual(len(evidence), 1)
        self.assertIn(COUNTRY_POLICY_SOURCE, evidence[0].source_ids)

    def test_a_restricted_country_says_so(self) -> None:
        _write_snapshot(self.root, _catalog())
        program = _program("SY")

        assertions, _ = _country_policy_assertions(program, self.root)

        self.assertIs(assertions[program.cases[0].case_id][0].value, True)

    def test_no_snapshot_states_nothing(self) -> None:
        """Which is the situation today. A country policy has to be dated and
        re-verifiable, and there is no defensible default — so the rule reports
        the fact as missing rather than being handed a guess."""
        program = _program("BR")

        assertions, evidence = _country_policy_assertions(program, self.root)

        self.assertEqual(assertions[program.cases[0].case_id], ())
        self.assertEqual(evidence, ())

    def test_an_unlisted_country_is_not_a_permissive_one(self) -> None:
        _write_snapshot(self.root, _catalog())
        program = _program("ZW")

        assertions, evidence = _country_policy_assertions(program, self.root)

        self.assertEqual(assertions[program.cases[0].case_id], ())
        self.assertEqual(evidence, ())

    def test_a_trade_with_no_country_asks_for_nothing(self) -> None:
        _write_snapshot(self.root, _catalog())
        program = _program(None)

        assertions, evidence = _country_policy_assertions(program, self.root)

        self.assertEqual(assertions[program.cases[0].case_id], ())
        self.assertEqual(evidence, ())

    def test_the_repository_still_has_no_country_snapshot(self) -> None:
        """A canary, not a wish. When Role A lands the snapshot this fails, and
        the failure is the reminder to raise the S4 acceptance baseline."""
        self.assertFalse(
            (LIVE_SNAPSHOTS / COUNTRY_POLICY_SOURCE).is_dir(),
            "국별인수방침 스냅샷이 생겼습니다 — S4 기준선을 올리고 이 시험을 지우세요",
        )


if __name__ == "__main__":
    unittest.main()
