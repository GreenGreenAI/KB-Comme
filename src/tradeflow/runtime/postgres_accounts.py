"""PostgreSQL account, tenant, session, analysis, and audit store."""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from tradeflow.runtime.accounts import (
    ACCOUNT_ROLES,
    LOGIN_LOCK,
    LOGIN_WINDOW,
    MAX_LOGIN_FAILURES,
    Account,
    _ABSENT_PASSWORD,
    _analysis_summary,
    _audit_material,
    _now,
    _session_key,
    hash_password,
    verify_password,
)


POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    password        TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    facts           JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS accounts_organization
    ON accounts(organization_id);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id      TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(account_id),
    packet_id   TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    result      JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS analysis_runs_tenant_time
    ON analysis_runs(account_id, created_at DESC);
CREATE TABLE IF NOT EXISTS consultation_events (
    event_id          TEXT PRIMARY KEY,
    organization_id   TEXT NOT NULL,
    analysis_run_id   TEXT NOT NULL REFERENCES analysis_runs(run_id),
    handoff_id        TEXT NOT NULL,
    status            TEXT NOT NULL,
    note              TEXT NOT NULL DEFAULT '',
    requested_items   JSONB NOT NULL DEFAULT '[]'::jsonb,
    recorded_by       TEXT NOT NULL,
    recorded_at       TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS consultation_events_tenant_run_time
    ON consultation_events(organization_id, analysis_run_id, recorded_at);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id         TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL,
    actor_account_id TEXT NOT NULL,
    action           TEXT NOT NULL,
    target_type      TEXT NOT NULL,
    target_id        TEXT,
    outcome          TEXT NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL,
    previous_hash    TEXT,
    event_hash       TEXT NOT NULL UNIQUE,
    details          JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_tenant_time
    ON audit_events(organization_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS login_attempts (
    identity_hash   TEXT PRIMARY KEY,
    failed_count    INTEGER NOT NULL,
    first_failed_at TIMESTAMPTZ NOT NULL,
    locked_until    TIMESTAMPTZ
);
CREATE OR REPLACE FUNCTION reject_audit_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit events are immutable';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;
CREATE TRIGGER audit_events_no_update
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE OR REPLACE FUNCTION reject_consultation_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'consultation events are immutable';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS consultation_events_no_update ON consultation_events;
CREATE TRIGGER consultation_events_no_update
BEFORE UPDATE OR DELETE ON consultation_events
FOR EACH ROW EXECUTE FUNCTION reject_consultation_mutation();
"""


class PostgresAccountStore:
    """Production store with the same behavioral contract as AccountStore."""

    def __init__(self, database_url: str) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("a PostgreSQL database URL is required")
        self.database_url = database_url
        with self._connect() as db:
            db.execute(POSTGRES_SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        with psycopg.connect(
            self.database_url,
            row_factory=dict_row,
        ) as db:
            yield db

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
        resolved = account_id or f"ACCOUNT-{secrets.token_hex(4).upper()}"
        account = Account(
            account_id=resolved,
            organization_id=organization_id or resolved,
            role=role,
            email=email.strip().lower(),
            company_name=company_name,
            facts=dict(facts or {}),
        )
        with self._connect() as db:
            db.execute(
                "INSERT INTO accounts"
                " (account_id, organization_id, role, email, password,"
                " company_name, facts) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (account_id) DO UPDATE SET"
                " organization_id = EXCLUDED.organization_id,"
                " role = EXCLUDED.role, email = EXCLUDED.email,"
                " password = EXCLUDED.password,"
                " company_name = EXCLUDED.company_name, facts = EXCLUDED.facts",
                (
                    account.account_id,
                    account.organization_id,
                    account.role,
                    account.email,
                    hash_password(password),
                    account.company_name,
                    Jsonb(account.facts),
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
        normalized = email.strip().lower()
        identity_hash = hashlib.sha256(normalized.encode()).hexdigest()
        moment = now or _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM accounts WHERE email = %s",
                (normalized,),
            ).fetchone()
            attempt = db.execute(
                "SELECT * FROM login_attempts WHERE identity_hash = %s",
                (identity_hash,),
            ).fetchone()
        # One real scrypt computation happens for both an absent and present
        # identity, preserving the enumeration-resistant timing contract.
        stored = row["password"] if row else _ABSENT_PASSWORD
        valid = verify_password(password, stored)
        locked = bool(
            attempt
            and attempt["locked_until"]
            and attempt["locked_until"] > moment
        )
        if valid and row and not locked:
            with self._connect() as db:
                db.execute(
                    "DELETE FROM login_attempts WHERE identity_hash = %s",
                    (identity_hash,),
                )
            return _account(row)
        if not locked:
            first = attempt["first_failed_at"] if attempt else moment
            if moment - first > LOGIN_WINDOW:
                first, count = moment, 1
            else:
                count = (attempt["failed_count"] if attempt else 0) + 1
            locked_until = moment + LOGIN_LOCK if count >= MAX_LOGIN_FAILURES else None
            with self._connect() as db:
                db.execute(
                    "INSERT INTO login_attempts"
                    " (identity_hash, failed_count, first_failed_at, locked_until)"
                    " VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (identity_hash) DO UPDATE SET"
                    " failed_count = EXCLUDED.failed_count,"
                    " first_failed_at = EXCLUDED.first_failed_at,"
                    " locked_until = EXCLUDED.locked_until",
                    (identity_hash, count, first, locked_until),
                )
        return None

    def find(self, account_id: str) -> Account | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM accounts WHERE account_id = %s",
                (account_id,),
            ).fetchone()
        return _account(row) if row else None

    def update_facts(self, account: Account, facts: dict[str, Any]) -> Account:
        merged = {**account.facts, **facts}
        with self._connect() as db:
            changed = db.execute(
                "UPDATE accounts SET facts = %s WHERE organization_id = %s",
                (Jsonb(merged), account.organization_id),
            ).rowcount
        if changed < 1:
            raise ValueError("account no longer exists")
        return Account(
            account_id=account.account_id,
            organization_id=account.organization_id,
            role=account.role,
            email=account.email,
            company_name=account.company_name,
            facts=merged,
        )

    def open_session(self, account: Account, *, now: datetime | None = None) -> str:
        from tradeflow.runtime.accounts import SESSION_DAYS
        from datetime import timedelta

        token = secrets.token_urlsafe(32)
        expires = (now or _now()) + timedelta(days=SESSION_DAYS)
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions (token, account_id, expires_at)"
                " VALUES (%s, %s, %s)",
                (_session_key(token), account.account_id, expires),
            )
        return token

    def read_session(self, token: str | None, *, now: datetime | None = None) -> Account | None:
        if not token:
            return None
        moment = now or _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT s.expires_at, a.* FROM sessions s"
                " JOIN accounts a ON a.account_id = s.account_id"
                " WHERE s.token = %s",
                (_session_key(token),),
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= moment:
            self.close_session(token)
            return None
        return _account(row)

    def close_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as db:
            db.execute(
                "DELETE FROM sessions WHERE token = %s",
                (_session_key(token),),
            )

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
                " VALUES (%s, %s, %s, %s, %s)",
                (
                    run_id,
                    account.account_id,
                    result.get("packet_id"),
                    now or _now(),
                    Jsonb(result),
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
                "SELECT r.run_id, r.packet_id, r.created_at, r.result"
                " FROM analysis_runs r JOIN accounts a"
                " ON a.account_id = r.account_id"
                " WHERE a.organization_id = %s"
                " ORDER BY r.created_at DESC LIMIT %s",
                (account.organization_id, limit),
            ).fetchall()
        return tuple(_analysis_summary(_json_result(row)) for row in rows)

    def read_analysis(
        self,
        account: Account,
        run_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT r.run_id, r.packet_id, r.created_at, r.result"
                " FROM analysis_runs r JOIN accounts a"
                " ON a.account_id = r.account_id"
                " WHERE a.organization_id = %s AND r.run_id = %s",
                (account.organization_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "packet_id": row["packet_id"],
            "created_at": row["created_at"].isoformat(),
            "result": row["result"],
        }

    def read_consultation(
        self,
        account: Account,
        run_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            rows = db.execute(
                "SELECT e.* FROM consultation_events e"
                " JOIN analysis_runs r ON r.run_id = e.analysis_run_id"
                " JOIN accounts a ON a.account_id = r.account_id"
                " WHERE e.organization_id = %s AND a.organization_id = %s"
                " AND e.analysis_run_id = %s"
                " ORDER BY e.recorded_at, e.event_id",
                (account.organization_id, account.organization_id, run_id),
            ).fetchall()
        if not rows:
            return None
        history = [_consultation_event(row) for row in rows]
        return {**history[-1], "history": history}

    def record_consultation_event(
        self,
        account: Account,
        run_id: str,
        *,
        handoff_id: str,
        status: str,
        note: str = "",
        requested_items: tuple[str, ...] = (),
        now: datetime | None = None,
    ) -> dict[str, Any]:
        from tradeflow.runtime.consultations import (
            validate_event_details,
            validate_transition,
        )

        requested_items = tuple(item.strip() for item in requested_items if item.strip())
        recorded_at = now or _now()
        event_id = f"CONSULT-{secrets.token_hex(12)}"
        with self._connect() as db:
            owned = db.execute(
                "SELECT 1 FROM analysis_runs r JOIN accounts a"
                " ON a.account_id = r.account_id"
                " WHERE a.organization_id = %s AND r.run_id = %s FOR UPDATE",
                (account.organization_id, run_id),
            ).fetchone()
            if owned is None:
                raise LookupError("analysis not found")
            previous = db.execute(
                "SELECT status FROM consultation_events"
                " WHERE organization_id = %s AND analysis_run_id = %s"
                " ORDER BY recorded_at DESC, event_id DESC LIMIT 1",
                (account.organization_id, run_id),
            ).fetchone()
            validate_transition(previous["status"] if previous else None, status)
            validate_event_details(status, note, requested_items)
            db.execute(
                "INSERT INTO consultation_events"
                " (event_id, organization_id, analysis_run_id, handoff_id,"
                " status, note, requested_items, recorded_by, recorded_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    event_id,
                    account.organization_id,
                    run_id,
                    handoff_id,
                    status,
                    note.strip(),
                    Jsonb(list(requested_items)),
                    account.email,
                    recorded_at,
                ),
            )
        consultation = self.read_consultation(account, run_id)
        assert consultation is not None
        return consultation

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
        event_id = f"AUDIT-{secrets.token_hex(12)}"
        occurred = now or _now()
        safe_details = dict(details or {})
        with self._connect() as db:
            # Serialize the per-tenant head update so concurrent requests cannot
            # fork the hash chain.
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (account.organization_id,),
            )
            previous = db.execute(
                "SELECT event_hash FROM audit_events"
                " WHERE organization_id = %s"
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
                occurred_at=occurred.isoformat(),
                previous_hash=previous_hash,
                details=safe_details,
            )
            event_hash = "sha256:" + hashlib.sha256(material.encode()).hexdigest()
            db.execute(
                "INSERT INTO audit_events"
                " (event_id, organization_id, actor_account_id, action,"
                " target_type, target_id, outcome, occurred_at, previous_hash,"
                " event_hash, details) VALUES"
                " (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    event_id,
                    account.organization_id,
                    account.account_id,
                    action,
                    target_type,
                    target_id,
                    outcome,
                    occurred,
                    previous_hash,
                    event_hash,
                    Jsonb(safe_details),
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
            "occurred_at": occurred.isoformat(),
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
                "SELECT * FROM audit_events WHERE organization_id = %s"
                " ORDER BY occurred_at DESC, event_id DESC LIMIT %s",
                (account.organization_id, limit),
            ).fetchall()
        return tuple(_audit_view(row) for row in rows)

    def verify_audit_chain(self, organization_id: str) -> bool:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_events WHERE organization_id = %s"
                " ORDER BY occurred_at, event_id",
                (organization_id,),
            ).fetchall()
        previous_hash = None
        for row in rows:
            expected = "sha256:" + hashlib.sha256(
                _audit_material(
                    event_id=row["event_id"],
                    organization_id=row["organization_id"],
                    actor_account_id=row["actor_account_id"],
                    action=row["action"],
                    target_type=row["target_type"],
                    target_id=row["target_id"],
                    outcome=row["outcome"],
                    occurred_at=row["occurred_at"].isoformat(),
                    previous_hash=previous_hash,
                    details=row["details"],
                ).encode()
            ).hexdigest()
            if row["previous_hash"] != previous_hash or row["event_hash"] != expected:
                return False
            previous_hash = row["event_hash"]
        return True


def _account(row: dict[str, Any]) -> Account:
    return Account(
        account_id=row["account_id"],
        organization_id=row["organization_id"],
        role=row["role"],
        email=row["email"],
        company_name=row["company_name"],
        facts=row["facts"] if isinstance(row["facts"], dict) else json.loads(row["facts"]),
    )


def _json_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "created_at": row["created_at"].isoformat(),
        "result": json.dumps(row["result"], ensure_ascii=False),
    }


def _audit_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "occurred_at": row["occurred_at"].isoformat(),
        "details": row["details"],
    }


def _consultation_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "analysis_run_id": row["analysis_run_id"],
        "handoff_id": row["handoff_id"],
        "status": row["status"],
        "note": row["note"],
        "requested_items": row["requested_items"],
        "recorded_by": row["recorded_by"],
        "recorded_at": row["recorded_at"].isoformat(),
        "verification": "user_recorded_not_bank_verified",
    }
