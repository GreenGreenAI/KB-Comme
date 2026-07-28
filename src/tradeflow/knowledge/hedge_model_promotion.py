"""Persistent, hash-bound hedge-model validation and promotion workflow."""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REQUIRED_APPROVALS = (
    "knowledge_domain",
    "platform_runtime",
    "domain_expert",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_runs (
    run_id       TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    report       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotion_requests (
    request_id      TEXT PRIMARY KEY,
    challenger_id   TEXT NOT NULL,
    validation_run  TEXT NOT NULL REFERENCES validation_runs(run_id),
    validation_hash TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotion_approvals (
    request_id      TEXT NOT NULL REFERENCES promotion_requests(request_id),
    role            TEXT NOT NULL,
    reviewer        TEXT NOT NULL,
    organization    TEXT,
    approved_at     TEXT NOT NULL,
    validation_hash TEXT NOT NULL,
    PRIMARY KEY (request_id, role)
);
"""


def canonical_json(document: Any) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_hash(document: Any) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(document).encode("utf-8")
    ).hexdigest()


class HedgeModelPromotionStore:
    """SQLite ledger whose approvals are bound to one validation hash."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def record_validation(
        self,
        report: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, str]:
        _validate_report(report)
        encoded = canonical_json(report)
        digest = content_hash(report)
        with self._connect() as db:
            existing = db.execute(
                "SELECT run_id, created_at FROM validation_runs"
                " WHERE content_hash = ?",
                (digest,),
            ).fetchone()
            if existing:
                return {
                    "run_id": existing["run_id"],
                    "content_hash": digest,
                    "created_at": existing["created_at"],
                }
            run_id = f"MODEL-RUN-{secrets.token_hex(10)}"
            created_at = (now or datetime.now(UTC)).isoformat()
            db.execute(
                "INSERT INTO validation_runs"
                " (run_id, content_hash, created_at, report)"
                " VALUES (?, ?, ?, ?)",
                (run_id, digest, created_at, encoded),
            )
        return {
            "run_id": run_id,
            "content_hash": digest,
            "created_at": created_at,
        }

    def request_promotion(
        self,
        challenger_id: str,
        validation_run: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        with self._connect() as db:
            validation = db.execute(
                "SELECT content_hash, report FROM validation_runs WHERE run_id = ?",
                (validation_run,),
            ).fetchone()
            if validation is None:
                raise ValueError("validation run does not exist")
            report = json.loads(validation["report"])
            model = (report.get("models") or {}).get(challenger_id)
            if model is None:
                raise ValueError("challenger is absent from validation report")
            promotion = model.get("promotion")
            if not promotion:
                raise ValueError("champion cannot be requested as a challenger")
            if not promotion.get("eligible"):
                blockers = promotion.get("blockers") or ["promotion gates failed"]
                raise ValueError("promotion blocked: " + "; ".join(blockers))
            if (report.get("benchmark") or {}).get("quote_basis") != (
                "observed_forward_quote"
            ):
                raise ValueError("promotion requires observed historical forward quotes")
            request_id = f"MODEL-PROMOTION-{secrets.token_hex(10)}"
            created_at = (now or datetime.now(UTC)).isoformat()
            db.execute(
                "INSERT INTO promotion_requests"
                " (request_id, challenger_id, validation_run, validation_hash,"
                " status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (
                    request_id,
                    challenger_id,
                    validation_run,
                    validation["content_hash"],
                    created_at,
                ),
            )
        return self.status(request_id)

    def approve(
        self,
        request_id: str,
        *,
        role: str,
        reviewer: str,
        organization: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if role not in REQUIRED_APPROVALS:
            raise ValueError(f"unsupported approval role: {role}")
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        if role == "domain_expert" and not (organization or "").strip():
            raise ValueError("domain expert organization is required")
        with self._connect() as db:
            request = db.execute(
                "SELECT validation_hash, status FROM promotion_requests"
                " WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if request is None:
                raise ValueError("promotion request does not exist")
            if request["status"] == "promoted":
                raise ValueError("promoted request cannot be changed")
            db.execute(
                "INSERT INTO promotion_approvals"
                " (request_id, role, reviewer, organization, approved_at,"
                " validation_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    role,
                    reviewer.strip(),
                    (organization or "").strip() or None,
                    (now or datetime.now(UTC)).isoformat(),
                    request["validation_hash"],
                ),
            )
        return self.status(request_id)

    def status(self, request_id: str) -> dict[str, Any]:
        with self._connect() as db:
            request = db.execute(
                "SELECT * FROM promotion_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if request is None:
                raise ValueError("promotion request does not exist")
            approvals = db.execute(
                "SELECT role, reviewer, organization, approved_at,"
                " validation_hash FROM promotion_approvals"
                " WHERE request_id = ? ORDER BY role",
                (request_id,),
            ).fetchall()
        approved_roles = {item["role"] for item in approvals}
        return {
            "request_id": request["request_id"],
            "challenger_id": request["challenger_id"],
            "validation_run": request["validation_run"],
            "validation_hash": request["validation_hash"],
            "status": request["status"],
            "created_at": request["created_at"],
            "approvals": [dict(item) for item in approvals],
            "missing_approvals": [
                role for role in REQUIRED_APPROVALS if role not in approved_roles
            ],
            "ready": (
                request["status"] == "pending"
                and approved_roles == set(REQUIRED_APPROVALS)
            ),
        }

    def promote(
        self,
        request_id: str,
        registry_path: Path | str,
    ) -> dict[str, Any]:
        status = self.status(request_id)
        if not status["ready"]:
            raise ValueError(
                "promotion approvals are incomplete: "
                + ", ".join(status["missing_approvals"])
            )
        path = Path(registry_path)
        registry = json.loads(path.read_text(encoding="utf-8"))
        models = {item["model_id"]: item for item in registry["models"]}
        challenger = models.get(status["challenger_id"])
        if challenger is None:
            raise ValueError("challenger is absent from governance registry")
        old_id = registry["champion_model_id"]
        old = models.get(old_id)
        if old is None or old.get("status") != "champion":
            raise ValueError("governance registry has no valid current champion")
        if challenger.get("status") != "challenger":
            raise ValueError("requested model is not an active challenger")

        old["status"] = "challenger"
        challenger["status"] = "champion"
        registry["champion_model_id"] = status["challenger_id"]
        path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self._connect() as db:
            db.execute(
                "UPDATE promotion_requests SET status = 'promoted'"
                " WHERE request_id = ? AND status = 'pending'",
                (request_id,),
            )
        return self.status(request_id)


def _validate_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise TypeError("validation report must be an object")
    if not isinstance(report.get("benchmark"), dict):
        raise ValueError("validation report benchmark is required")
    models = report.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError("validation report models are required")
    for model_id, model in models.items():
        if not isinstance(model, dict) or model.get("tested", 0) < 1:
            raise ValueError(f"{model_id}: tested origins are required")
