import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tradeflow.runtime.accounts import (
    AccountStore,
    hash_password,
    verify_password,
)


class PasswordTests(unittest.TestCase):
    def test_the_stored_value_is_not_the_password(self) -> None:
        stored = hash_password("tradeflow-demo")
        self.assertNotIn("tradeflow-demo", stored)
        self.assertTrue(verify_password("tradeflow-demo", stored))
        self.assertFalse(verify_password("tradeflow-dem", stored))

    def test_the_same_password_stores_differently_each_time(self) -> None:
        """Per-account salt. Two companies choosing the same weak password must
        not produce the same row, or cracking one cracks both."""
        self.assertNotEqual(hash_password("same"), hash_password("same"))

    def test_a_malformed_stored_value_fails_closed(self) -> None:
        for junk in ("", "no-separator", "zz$zz"):
            with self.subTest(junk=junk):
                self.assertFalse(verify_password("anything", junk))


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = AccountStore(Path(self._dir.name) / "accounts.db")
        self.account = self.store.create(
            "kim@hanbit.co.kr",
            "tradeflow-demo",
            company_name="한빛정밀",
            facts={"company.is_sme": True, "company.size": "small"},
            account_id="COMPANY-HANBIT",
        )

    def test_authentication_needs_the_password(self) -> None:
        self.assertIsNotNone(
            self.store.authenticate("kim@hanbit.co.kr", "tradeflow-demo")
        )
        self.assertIsNone(self.store.authenticate("kim@hanbit.co.kr", "wrong"))

    def test_the_address_is_matched_case_insensitively(self) -> None:
        self.assertIsNotNone(
            self.store.authenticate("  KIM@Hanbit.co.kr ", "tradeflow-demo")
        )

    def test_a_missing_account_costs_the_same_as_a_wrong_password(self) -> None:
        """Otherwise the login form answers a question nobody asked — whether a
        given company has an account here — through how fast it says no."""

        def elapsed(email: str) -> float:
            start = time.perf_counter()
            self.store.authenticate(email, "wrong-password")
            return time.perf_counter() - start

        wrong = min(elapsed("kim@hanbit.co.kr") for _ in range(3))
        absent = min(elapsed("nobody@example.com") for _ in range(3))
        # Generous: the point is that the absent case still pays for a hash, not
        # that the two are identical to the microsecond.
        self.assertGreater(absent, wrong * 0.5)

    def test_a_session_names_its_account(self) -> None:
        token = self.store.open_session(self.account)
        seen = self.store.read_session(token)
        self.assertIsNotNone(seen)
        self.assertEqual(seen.account_id, "COMPANY-HANBIT")

    def test_signing_out_kills_the_token_on_the_server(self) -> None:
        """Dropping the cookie is not signing out. A copy of the token must stop
        working too."""
        token = self.store.open_session(self.account)
        self.store.close_session(token)
        self.assertIsNone(self.store.read_session(token))

    def test_an_expired_session_stops_working_when_it_expires(self) -> None:
        token = self.store.open_session(
            self.account, now=datetime.now(timezone.utc) - timedelta(days=90)
        )
        self.assertIsNone(self.store.read_session(token))

    def test_an_unknown_token_is_nobody(self) -> None:
        self.assertIsNone(self.store.read_session("made-up"))
        self.assertIsNone(self.store.read_session(None))


class ProfileTests(unittest.TestCase):
    """The account is where §5.4's company facts come from."""

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = AccountStore(Path(self._dir.name) / "accounts.db")

    def _profile(self, facts):
        account = self.store.create(
            "a@b.co.kr", "pw", company_name="한빛정밀", facts=facts
        )
        return account.profile()

    def test_rule_facts_reach_the_profile_under_their_own_names(self) -> None:
        profile = self._profile(
            {
                "company.is_sme": True,
                "company.size": "small",
                "company.credit_issue_free": True,
                "company.ksure_exporter_grade": "A",
            }
        )
        facts = profile.facts()
        self.assertEqual(facts["company.size"], "small")
        self.assertIs(facts["company.credit_issue_free"], True)
        self.assertEqual(facts["company.ksure_exporter_grade"], "A")
        self.assertIs(facts["company.is_sme"], True)

    def test_a_fact_the_account_does_not_state_stays_absent(self) -> None:
        """Not False. §1.1: a missing fact is a question, and answering it with
        a default is exactly the guess this product refuses to make."""
        facts = self._profile({"company.is_sme": True}).facts()
        self.assertNotIn("company.size", facts)
        self.assertNotIn("company.credit_issue_free", facts)

    def test_reserved_facts_do_not_collide(self) -> None:
        """`CompanyProfile` rejects attributes that shadow its core fields, so
        these have to be lifted rather than passed through."""
        profile = self._profile(
            {"company.is_sme": False, "company.industry_code": "C29"}
        )
        self.assertIs(profile.is_sme, False)
        self.assertEqual(profile.industry_code, "C29")


if __name__ == "__main__":
    unittest.main()
