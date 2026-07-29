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
    account_id   TEXT PRIMARY KEY,
    email        TEXT NOT NULL UNIQUE,
    password     TEXT NOT NULL,
    company_name TEXT NOT NULL,
    facts        TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    identity_hash   TEXT PRIMARY KEY,
    failed_count    INTEGER NOT NULL,
    first_failed_at TEXT NOT NULL,
    locked_until    TEXT
);
"""


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
    email: str
    company_name: str
    facts: dict[str, Any] = field(default_factory=dict)

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
            company_id=self.account_id,
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
    ) -> Account:
        account = Account(
            account_id=account_id or f"COMPANY-{secrets.token_hex(4).upper()}",
            email=email.strip().lower(),
            company_name=company_name,
            facts=dict(facts or {}),
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO accounts"
                " (account_id, email, password, company_name, facts)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    account.account_id,
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
            self._record_login_failure(identity_hash, attempt, now=moment)
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


#: A real-looking hash that no password matches, so authenticating a
#: non-existent account does the same work as authenticating a real one.
_ABSENT_PASSWORD = hash_password(secrets.token_urlsafe(32))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=row["account_id"],
        email=row["email"],
        company_name=row["company_name"],
        facts=json.loads(row["facts"] or "{}"),
    )
