import time
import unittest
import contextlib
import sqlite3
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

    def test_repeated_failures_temporarily_lock_even_the_correct_password(self) -> None:
        now = datetime.now(timezone.utc)
        for offset in range(5):
            self.assertIsNone(
                self.store.authenticate(
                    "kim@hanbit.co.kr",
                    "wrong",
                    now=now + timedelta(seconds=offset),
                )
            )

        self.assertIsNone(
            self.store.authenticate(
                "kim@hanbit.co.kr",
                "tradeflow-demo",
                now=now + timedelta(minutes=1),
            )
        )
        self.assertIsNotNone(
            self.store.authenticate(
                "kim@hanbit.co.kr",
                "tradeflow-demo",
                now=now + timedelta(minutes=16),
            )
        )


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


class TenantAnalysisStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.store = AccountStore(Path(self._dir.name) / "accounts.db")
        self.alpha = self.store.create(
            "alpha@example.com",
            "pw",
            company_name="알파",
            account_id="COMPANY-ALPHA",
        )
        self.beta = self.store.create(
            "beta@example.com",
            "pw",
            company_name="베타",
            account_id="COMPANY-BETA",
        )

    def result(self, company: str) -> dict:
        return {
            "packet_id": f"packet:{company}",
            "company_profile": {"company_name": company},
            "trade_timeline": [{"case_id": "EXPORT-001"}],
            "review_required": True,
        }

    def test_company_facts_are_merged_without_replacing_identity(self) -> None:
        updated = self.store.update_facts(
            self.alpha,
            {"company.size": "small"},
        )

        self.assertEqual("COMPANY-ALPHA", updated.account_id)
        self.assertEqual(
            "small", self.store.find("COMPANY-ALPHA").facts["company.size"]
        )

    def test_analysis_history_is_scoped_to_the_authenticated_tenant(self) -> None:
        alpha_run = self.store.save_analysis(self.alpha, self.result("알파"))
        self.store.save_analysis(self.beta, self.result("베타"))

        alpha_history = self.store.list_analyses(self.alpha)
        self.assertEqual(1, len(alpha_history))
        self.assertEqual(alpha_run, alpha_history[0]["run_id"])
        self.assertEqual("알파", alpha_history[0]["company_name"])

    def test_cross_tenant_run_id_is_not_readable(self) -> None:
        alpha_run = self.store.save_analysis(self.alpha, self.result("알파"))

        self.assertIsNone(self.store.read_analysis(self.beta, alpha_run))
        stored = self.store.read_analysis(self.alpha, alpha_run)
        self.assertEqual("알파", stored["result"]["company_profile"]["company_name"])


class OrganizationRbacAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "accounts.db"
        self.store = AccountStore(self.path)
        self.admin = self.store.create(
            "admin@example.com",
            "pw",
            company_name="Alpha",
            account_id="ACCOUNT-ADMIN",
            organization_id="ORG-ALPHA",
            role="company_admin",
        )
        self.user = self.store.create(
            "user@example.com",
            "pw",
            company_name="Alpha",
            account_id="ACCOUNT-USER",
            organization_id="ORG-ALPHA",
            role="company_user",
        )
        self.other = self.store.create(
            "other@example.com",
            "pw",
            company_name="Beta",
            account_id="ACCOUNT-OTHER",
            organization_id="ORG-BETA",
            role="company_admin",
        )

    def test_permissions_are_least_privilege_and_profile_uses_organization(self) -> None:
        self.assertTrue(self.admin.can("audit:read"))
        self.assertFalse(self.user.can("audit:read"))
        self.assertTrue(self.user.can("document:upload"))
        self.assertFalse(
            self.store.create(
                "rm@example.com",
                "pw",
                company_name="Bank",
                role="rm",
            ).can("analysis:read")
        )
        self.assertEqual("ORG-ALPHA", self.user.profile().company_id)

    def test_analysis_history_is_shared_inside_org_but_not_across_orgs(self) -> None:
        run_id = self.store.save_analysis(
            self.user,
            {
                "packet_id": "packet:1",
                "company_profile": {"company_name": "Alpha"},
                "trade_timeline": [],
            },
        )

        self.assertIsNotNone(self.store.read_analysis(self.admin, run_id))
        self.assertIsNone(self.store.read_analysis(self.other, run_id))

    def test_profile_fact_update_is_shared_by_every_account_in_the_org(self) -> None:
        self.store.update_facts(self.admin, {"company.size": "small"})

        self.assertEqual(
            "small",
            self.store.find(self.user.account_id).facts["company.size"],
        )
        self.assertNotIn("company.size", self.store.find(self.other.account_id).facts)

    def test_session_database_contains_only_a_token_hash(self) -> None:
        token = self.store.open_session(self.admin)
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            stored = db.execute("SELECT token FROM sessions").fetchone()[0]

        self.assertNotEqual(token, stored)
        self.assertNotIn(token, stored)
        self.assertIsNotNone(self.store.read_session(token))

    def test_audit_chain_is_tenant_scoped_hash_chained_and_immutable(self) -> None:
        first = self.store.append_audit(
            self.admin,
            action="document.upload",
            target_type="document",
            target_id="DOC-1",
            details={"content_hash": "sha256:test"},
        )
        second = self.store.append_audit(
            self.user,
            action="document.read",
            target_type="document",
            target_id="DOC-1",
        )
        self.store.append_audit(
            self.other,
            action="analysis.create",
            target_type="analysis",
            target_id="RUN-2",
        )

        events = self.store.list_audit(self.admin)
        self.assertEqual(2, len(events))
        self.assertEqual(first["event_hash"], second["previous_hash"])
        self.assertTrue(self.store.verify_audit_chain("ORG-ALPHA"))
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE audit_events SET action = 'tampered'"
                    " WHERE event_id = ?",
                    (first["event_id"],),
                )


if __name__ == "__main__":
    unittest.main()
