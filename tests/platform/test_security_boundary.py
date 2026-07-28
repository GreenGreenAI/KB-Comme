import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tradeflow.runtime.accounts import AccountStore
from tradeflow.web.app import (
    AnalyzeRequest,
    ProfileFactsRequest,
    analyze_endpoint,
    app,
    audit_events,
    update_profile,
)


class RbacBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.accounts = AccountStore(Path(self.directory.name) / "accounts.db")
        self.admin = self.accounts.create(
            "admin@example.com",
            "pw",
            company_name="Alpha",
            account_id="ACCOUNT-ADMIN",
            organization_id="ORG-A",
            role="company_admin",
        )
        self.user = self.accounts.create(
            "user@example.com",
            "pw",
            company_name="Alpha",
            account_id="ACCOUNT-USER",
            organization_id="ORG-A",
            role="company_user",
        )
        self.rm = self.accounts.create(
            "rm@example.com",
            "pw",
            company_name="Bank",
            account_id="ACCOUNT-RM",
            organization_id="ORG-BANK",
            role="rm",
        )
        self.admin_token = self.accounts.open_session(self.admin)
        self.user_token = self.accounts.open_session(self.user)
        self.rm_token = self.accounts.open_session(self.rm)
        self.patch = patch("tradeflow.web.app.accounts", self.accounts)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_company_user_cannot_change_org_profile_and_denial_is_audited(self) -> None:
        with self.assertRaises(HTTPException) as context:
            update_profile(
                ProfileFactsRequest(facts={"company.size": "large"}),
                session=self.user_token,
            )

        self.assertEqual(403, context.exception.status_code)
        events = self.accounts.list_audit(self.admin)
        self.assertEqual("denied", events[0]["outcome"])
        self.assertEqual("authorization.profile:write", events[0]["action"])

    def test_unassigned_rm_does_not_gain_customer_analysis_access(self) -> None:
        with self.assertRaises(HTTPException) as context:
            analyze_endpoint(AnalyzeRequest(), session=self.rm_token)

        self.assertEqual(403, context.exception.status_code)

    def test_admin_can_read_tenant_audit_and_chain_verification(self) -> None:
        self.accounts.append_audit(
            self.user,
            action="analysis.read",
            target_type="analysis",
            target_id="RUN-1",
        )
        result = audit_events(limit=20, session=self.admin_token)

        self.assertTrue(result["chain_valid"])
        self.assertEqual("audit.read", result["events"][0]["action"])


class HttpSecurityHeaderTests(unittest.TestCase):
    def test_responses_set_browser_security_headers(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/health")

        self.assertEqual("nosniff", response.headers["x-content-type-options"])
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual("no-referrer", response.headers["referrer-policy"])

    def test_state_change_from_unknown_origin_is_rejected(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/login",
                headers={"Origin": "https://attacker.invalid"},
                json={"email": "nobody@example.com", "password": "wrong"},
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual(
            "허용되지 않은 요청 출처입니다",
            response.json()["detail"]["reason"],
        )


if __name__ == "__main__":
    unittest.main()
