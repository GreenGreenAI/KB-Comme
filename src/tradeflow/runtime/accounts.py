"""Accounts, sessions, and the company facts an account carries.

Signing in is not a gate in this product. It is where `CompanyProfile` comes
from. §5.4's eligibility rules read facts about the company — its size, whether
it is free of credit issues, its K-SURE exporter grade — and those belong to the
company, not to each request. Carrying them in the request body meant the screen
could show "한빛정밀 · 중소기업" while the analysis was run for a nameless
company with no facts at all. An account is where that stops being possible.

The store is SQLite through the standard library. `pyproject.toml` keeps
`dependencies = []` so CI runs without installing anything, and password
hashing, session tokens and storage are all reachable without breaking that:
`hashlib.scrypt`, `secrets`, `sqlite3`.

This module knows nothing about HTTP. Cookies, status codes and the shape of
the login form live in `web`; what is here is what an account *is*, so it can be
tested without a server.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradeflow.domain.models import CompanyProfile

#: scrypt parameters. The cost is the point — it is the difference between a
#: leaked table being cracked in an afternoon and not being worth the
#: electricity.
#:
#: `maxmem` is passed explicitly because OpenSSL's default ceiling is 32 MiB and
#: these parameters need exactly that (128·N·r), so the default raises "memory
#: limit exceeded" rather than working. Leaving it out and dropping to n=2^14 to
#: make the error go away would have quietly halved the cost.
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024

#: How long a session lives. Long enough that a demo is not interrupted, short
#: enough that a forgotten browser is not an open door.
SESSION_DAYS = 14
MAX_LOGIN_FAILURES = 5
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_LOCK = timedelta(minutes=15)

#: `CompanyProfile` refuses to let attributes shadow these — a fact stated twice
#: with two values is worse than a fact stated once. They are lifted into the
#: core fields instead of being dropped.
RESERVED_FACTS = frozenset({
    "company.is_sme",
    "company.country_code",
    "company.annual_export_usd",
    "company.industry_code",
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT PRIMARY KEY,
    organization_id TEXT,
    role            TEXT NOT NULL DEFAULT 'company_admin',
    email           TEXT NOT NULL UNIQUE,
    password        TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    facts           TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id      TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(account_id),
    packet_id   TEXT,
    created_at  TEXT NOT NULL,
    result      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analysis_runs_tenant_time
    ON analysis_runs(account_id, created_at DESC);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id         TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL,
    actor_account_id TEXT NOT NULL,
    action           TEXT NOT NULL,
    target_type      TEXT NOT NULL,
    target_id        TEXT,
    outcome          TEXT NOT NULL,
    occurred_at      TEXT NOT NULL,
    previous_hash    TEXT,
    event_hash       TEXT NOT NULL UNIQUE,
    details          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_tenant_time
    ON audit_events(organization_id, occurred_at DESC);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are immutable');
END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are immutable');
END;
CREATE TABLE IF NOT EXISTS login_attempts (
    identity_hash   TEXT PRIMARY KEY,
    failed_count    INTEGER NOT NULL,
    first_failed_at TEXT NOT NULL,
    locked_until    TEXT
);
"""

ACCOUNT_ROLES = frozenset(
    {
        "company_user",
        "company_admin",
        "rm",
        "data_admin",
        "operations_admin",
    }
)
ROLE_PERMISSIONS = {
    "company_user": frozenset(
        {
            "analysis:read",
            "analysis:write",
            "document:read",
            "document:upload",
            "document:confirm",
            "document:check",
        }
    ),
    "company_admin": frozenset(
        {
            "analysis:read",
            "analysis:write",
            "document:read",
            "document:upload",
            "document:confirm",
            "document:check",
            "profile:write",
            "audit:read",
        }
    ),
    "rm": frozenset(),
    "data_admin": frozenset({"knowledge:write"}),
    "operations_admin": frozenset({"operations:read"}),
}


@dataclass(frozen=True)
class Account:
    """Who is signed in, and what is known about their company.

    `facts` holds the §5.4 fact names verbatim — `company.size`,
    `company.credit_issue_free`, `company.ksure_exporter_grade`. They are not
    renamed on the way in, so a rule that asks for a fact and an account that
    states it are talking about the same string, and a typo is a missing fact
    rather than a silently different one.
    """

    account_id: str
    organization_id: str
    role: str
    email: str
    company_name: str
    facts: dict[str, Any] = field(default_factory=dict)

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]

    def profile(self) -> CompanyProfile:
        """The company as the analysis will see it.

        `is_sme` is lifted out because `CompanyProfile` reserves it as a core
        field; the rest ride in `attributes`, which is where §5.4 reads them
        from. Anything the account does not state stays absent — an unstated
        fact is a question the rules will ask, never a `False` we invented.
        """
        attributes = {
            name: value
            for name, value in self.facts.items()
            if name not in RESERVED_FACTS
        }
        return CompanyProfile(
            company_id=self.organization_id,
            name=self.company_name,
            is_sme=self.facts.get("company.is_sme"),
            country_code=self.facts.get("company.country_code", "KR"),
            industry_code=self.facts.get("company.industry_code"),
            attributes=attributes,
        )


def hash_password(password: str) -> str:
    """A salted scrypt digest, stored as `salt$digest` in hex.

    The salt is per-account and stored beside the digest: it is not a secret,
    it exists so that two accounts with the same password do not produce the
    same row, and so a precomputed table is worth nothing.
    """
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_DKLEN)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Compare in constant time.

    A plain `==` on digests leaks how many leading bytes matched through how
    long it took to say no.
    """
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = _scrypt(password, salt, len(expected) or SCRYPT_DKLEN)
    return hmac.compare_digest(candidate, expected)


def _scrypt(password: str, salt: bytes, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=dklen,
        maxmem=SCRYPT_MAXMEM,
    )


class AccountStore:
    """Accounts and their sessions, in one SQLite file."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(accounts)").fetchall()
            }
            if "organization_id" not in columns:
                db.execute("ALTER TABLE accounts ADD COLUMN organization_id TEXT")
            if "role" not in columns:
                db.execute(
                    "ALTER TABLE accounts ADD COLUMN role TEXT"
                    " NOT NULL DEFAULT 'company_admin'"
                )
            db.execute(
                "UPDATE accounts SET organization_id = account_id"
                " WHERE organization_id IS NULL OR organization_id = ''"
            )

    @contextlib.contextmanager
    def _connect(self):
        """Commit and close.

        `sqlite3.Connection` as a context manager commits but does not close —
        the file handle stays open until the object is collected, which on a
        long-running server is a handle per request.
        """
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---- accounts ----

    def create(
        self,
        email: str,
        password: str,
        *,
        company_name: str,
        facts: dict[str, Any] | None = None,
        account_id: str | None = None,
        organization_id: str | None = None,
        role: str = "company_admin",
    ) -> Account:
        if role not in ACCOUNT_ROLES:
            raise ValueError(f"unsupported account role: {role}")
        resolved_account_id = (
            account_id or f"ACCOUNT-{secrets.token_hex(4).upper()}"
        )
        account = Account(
            account_id=resolved_account_id,
            organization_id=organization_id or resolved_account_id,
            role=role,
            email=email.strip().lower(),
            company_name=company_name,
            facts=dict(facts or {}),
        )
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO accounts"
                " (account_id, organization_id, role, email, password,"
                " company_name, facts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    account.account_id,
                    account.organization_id,
                    account.role,
                    account.email,
                    hash_password(password),
                    account.company_name,
                    json.dumps(account.facts, ensure_ascii=False),
                ),
            )
        return account

    def authenticate(
        self,
        email: str,
        password: str,
        *,
        now: datetime | None = None,
    ) -> Account | None:
        """The account, or nothing — and the two failures cost the same.

        A missing account still pays for one scrypt hash. Returning early would
        make "no such account" measurably faster than "wrong password", which
        turns the login form into a way to enumerate who has an account here.
        """
        normalized_email = email.strip().lower()
        identity_hash = hashlib.sha256(
            normalized_email.encode("utf-8")
        ).hexdigest()
        moment = now or _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM accounts WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            attempt = db.execute(
                "SELECT * FROM login_attempts WHERE identity_hash = ?",
                (identity_hash,),
            ).fetchone()

        stored = row["password"] if row else _ABSENT_PASSWORD
        password_valid = verify_password(password, stored)
        locked = bool(
            attempt
            and attempt["locked_until"]
            and datetime.fromisoformat(attempt["locked_until"]) > moment
        )
        if password_valid and row is not None and not locked:
            with self._connect() as db:
                db.execute(
                    "DELETE FROM login_attempts WHERE identity_hash = ?",
                    (identity_hash,),
                )
            return _account(row)
        if not locked:
            self._record_login_failure(
                identity_hash,
                attempt,
                now=moment,
            )
        if not password_valid:
            return None
        return None

    def _record_login_failure(
        self,
        identity_hash: str,
        attempt: sqlite3.Row | None,
        *,
        now: datetime,
    ) -> None:
        first = (
            datetime.fromisoformat(attempt["first_failed_at"])
            if attempt
            else now
        )
        if now - first > LOGIN_WINDOW:
            first = now
            count = 1
        else:
            count = (attempt["failed_count"] if attempt else 0) + 1
        locked_until = (
            (now + LOGIN_LOCK).isoformat()
            if count >= MAX_LOGIN_FAILURES
            else None
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO login_attempts"
                " (identity_hash, failed_count, first_failed_at, locked_until)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(identity_hash) DO UPDATE SET"
                " failed_count = excluded.failed_count,"
                " first_failed_at = excluded.first_failed_at,"
                " locked_until = excluded.locked_until",
                (identity_hash, count, first.isoformat(), locked_until),
            )

    def find(self, account_id: str) -> Account | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
        return _account(row) if row else None

    def update_facts(
        self,
        account: Account,
        facts: dict[str, Any],
    ) -> Account:
        """Merge company facts under the authenticated account's tenant."""
        merged = {**account.facts, **facts}
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE accounts SET facts = ? WHERE organization_id = ?",
                (
                    json.dumps(merged, ensure_ascii=False),
                    account.organization_id,
                ),
            )
            if cursor.rowcount < 1:
                raise ValueError("account no longer exists")
        return Account(
            account_id=account.account_id,
            organization_id=account.organization_id,
            role=account.role,
            email=account.email,
            company_name=account.company_name,
            facts=merged,
        )

    # ---- sessions ----

    def open_session(self, account: Account, *, now: datetime | None = None) -> str:
        token = secrets.token_urlsafe(32)
        expires = (now or _now()) + timedelta(days=SESSION_DAYS)
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions (token, account_id, expires_at) VALUES (?, ?, ?)",
                (_session_key(token), account.account_id, expires.isoformat()),
            )
        return token

    def read_session(self, token: str | None, *, now: datetime | None = None) -> Account | None:
        """Who this token belongs to, if it is still good.

        Expiry is checked here rather than swept on a timer: a session that has
        run out must stop working the moment it runs out, whether or not
        anything has cleaned up after it.
        """
        if not token:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT s.expires_at, a.* FROM sessions s"
                " JOIN accounts a ON a.account_id = s.account_id"
                " WHERE s.token = ?",
                (_session_key(token),),
            ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= (now or _now()):
            self.close_session(token)
            return None
        return _account(row)

    def close_session(self, token: str | None) -> None:
        """Sign out on the server, not just in the browser.

        Dropping the cookie alone would leave a token that still works to
        anyone who kept a copy of it.
        """
        if not token:
            return
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (_session_key(token),))

    # ---- tenant-scoped analysis history ----

    def save_analysis(
        self,
        account: Account,
        result: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> str:
        run_id = f"RUN-{secrets.token_hex(12)}"
        with self._connect() as db:
            db.execute(
                "INSERT INTO analysis_runs"
                " (run_id, account_id, packet_id, created_at, result)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    account.account_id,
                    result.get("packet_id"),
                    (now or _now()).isoformat(),
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        return run_id

    def list_analyses(
        self,
        account: Account,
        *,
        limit: int = 20,
    ) -> tuple[dict[str, Any], ...]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as db:
            rows = db.execute(
                "SELECT run_id, packet_id, created_at, result"
                " FROM analysis_runs"
                " WHERE account_id IN ("
                " SELECT account_id FROM accounts WHERE organization_id = ?"
                " )"
                " ORDER BY created_at DESC LIMIT ?",
                (account.organization_id, limit),
            ).fetchall()
        return tuple(_analysis_summary(row) for row in rows)

    def read_analysis(
        self,
        account: Account,
        run_id: str,
    ) -> dict[str, Any] | None:
        """Read through both identifiers so cross-tenant IDs reveal nothing."""
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id, packet_id, created_at, result"
                " FROM analysis_runs"
                " WHERE account_id IN ("
                " SELECT account_id FROM accounts WHERE organization_id = ?"
                " ) AND run_id = ?",
                (account.organization_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "packet_id": row["packet_id"],
            "created_at": row["created_at"],
            "result": json.loads(row["result"]),
        }

    # ---- append-only audit trail ----

    def append_audit(
        self,
        account: Account,
        *,
        action: str,
        target_type: str,
        target_id: str | None = None,
        outcome: str = "success",
        details: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if outcome not in {"success", "denied", "failed"}:
            raise ValueError("unsupported audit outcome")
        occurred_at = (now or _now()).isoformat()
        event_id = f"AUDIT-{secrets.token_hex(12)}"
        safe_details = dict(details or {})
        encoded_details = json.dumps(
            safe_details,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as db:
            previous = db.execute(
                "SELECT event_hash FROM audit_events"
                " WHERE organization_id = ?"
                " ORDER BY occurred_at DESC, event_id DESC LIMIT 1",
                (account.organization_id,),
            ).fetchone()
            previous_hash = previous["event_hash"] if previous else None
            material = _audit_material(
                event_id=event_id,
                organization_id=account.organization_id,
                actor_account_id=account.account_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                occurred_at=occurred_at,
                previous_hash=previous_hash,
                details=safe_details,
            )
            event_hash = "sha256:" + hashlib.sha256(
                material.encode("utf-8")
            ).hexdigest()
            db.execute(
                "INSERT INTO audit_events"
                " (event_id, organization_id, actor_account_id, action,"
                " target_type, target_id, outcome, occurred_at, previous_hash,"
                " event_hash, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    account.organization_id,
                    account.account_id,
                    action,
                    target_type,
                    target_id,
                    outcome,
                    occurred_at,
                    previous_hash,
                    event_hash,
                    encoded_details,
                ),
            )
        return {
            "event_id": event_id,
            "organization_id": account.organization_id,
            "actor_account_id": account.account_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "outcome": outcome,
            "occurred_at": occurred_at,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
            "details": safe_details,
        }

    def list_audit(
        self,
        account: Account,
        *,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_events WHERE organization_id = ?"
                " ORDER BY occurred_at DESC, event_id DESC LIMIT ?",
                (account.organization_id, limit),
            ).fetchall()
        return tuple(
            {
                **dict(row),
                "details": json.loads(row["details"]),
            }
            for row in rows
        )

    def verify_audit_chain(self, organization_id: str) -> bool:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_events WHERE organization_id = ?"
                " ORDER BY occurred_at, event_id",
                (organization_id,),
            ).fetchall()
        previous_hash = None
        for row in rows:
            details = json.loads(row["details"])
            expected = "sha256:" + hashlib.sha256(
                _audit_material(
                    event_id=row["event_id"],
                    organization_id=row["organization_id"],
                    actor_account_id=row["actor_account_id"],
                    action=row["action"],
                    target_type=row["target_type"],
                    target_id=row["target_id"],
                    outcome=row["outcome"],
                    occurred_at=row["occurred_at"],
                    previous_hash=previous_hash,
                    details=details,
                ).encode("utf-8")
            ).hexdigest()
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
                return False
            previous_hash = row["event_hash"]
        return True


#: A real-looking hash that no password matches, so authenticating a
#: non-existent account does the same work as authenticating a real one.
_ABSENT_PASSWORD = hash_password(secrets.token_urlsafe(32))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _audit_material(**values: Any) -> str:
    return json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=row["account_id"],
        organization_id=row["organization_id"] or row["account_id"],
        role=row["role"],
        email=row["email"],
        company_name=row["company_name"],
        facts=json.loads(row["facts"] or "{}"),
    )


def _analysis_summary(row: sqlite3.Row) -> dict[str, Any]:
    result = json.loads(row["result"])
    profile = result.get("company_profile") or {}
    return {
        "run_id": row["run_id"],
        "packet_id": row["packet_id"],
        "created_at": row["created_at"],
        "company_name": profile.get("company_name"),
        "trade_count": len(result.get("trade_timeline") or []),
        "review_required": bool(result.get("review_required")),
    }
