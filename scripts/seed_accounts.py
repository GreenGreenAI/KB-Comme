"""Create the demo accounts the sign-in screen expects.

There is no sign-up. Building one would mean email verification, duplicate
handling and a password policy — real work that proves nothing about this
product, whose subject is FX risk and not identity. What has to be real is what
an account *does*: hold the company facts §5.4 reads, so the screen and the
analysis cannot disagree about who the company is.

The facts below use §5.4's own names. `company.size` and
`company.credit_issue_free` are what the K-SURE eligibility rules ask for by
name; stating them here is what turns "기업규모와 신용 상태를 알려주시면
판정합니다" into an actual judgement.

    python scripts/seed_accounts.py

Writes to data/accounts.db, `$TRADEFLOW_ACCOUNT_DB`, or a non-production
`$TRADEFLOW_DATABASE_URL`. It refuses production because these credentials are
public demo fixtures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradeflow.runtime.accounts import AccountStore  # noqa: E402
from tradeflow.runtime.postgres_accounts import PostgresAccountStore  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("TRADEFLOW_ACCOUNT_DB", REPO_ROOT / "data" / "accounts.db"))
DATABASE_URL = os.environ.get("TRADEFLOW_DATABASE_URL")

#: One account that can be judged and one that cannot, on purpose. The second
#: exists so the "부족하면 멈춘다" path stays visible in a demo — a screen where
#: every account happens to satisfy every rule would never show it.
SEEDS = [
    {
        "email": "kim@hanbit.co.kr",
        "password": "tradeflow-demo",
        "company_name": "한빛정밀",
        "account_id": "COMPANY-HANBIT",
        "facts": {
            "company.is_sme": True,
            "company.size": "small",
            "company.is_domestic": True,
            "company.credit_issue_free": True,
            "company.ksure_exporter_grade": "A",
            "company.industry_code": "C29",
        },
    },
    {
        "email": "park@saeron.co.kr",
        "password": "tradeflow-demo",
        "company_name": "새론무역",
        "account_id": "COMPANY-SAERON",
        "facts": {
            "company.is_sme": True,
            "company.is_domestic": True,
            "company.industry_code": "G46",
        },
    },
]


def main() -> int:
    if os.environ.get("TRADEFLOW_ENV") == "production":
        raise RuntimeError("demo accounts must not be seeded in production")
    store = PostgresAccountStore(DATABASE_URL) if DATABASE_URL else AccountStore(DB_PATH)
    for seed in SEEDS:
        account = store.create(
            seed["email"],
            seed["password"],
            company_name=seed["company_name"],
            facts=seed["facts"],
            account_id=seed["account_id"],
            organization_id=seed["account_id"],
            role="company_admin",
        )
        stated = len(account.facts)
        print(f"{account.email:24} {account.company_name:8} 기업 사실 {stated}건")
    print(f"\n{'PostgreSQL' if DATABASE_URL else DB_PATH}")
    print("비밀번호는 두 계정 모두 tradeflow-demo 입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
