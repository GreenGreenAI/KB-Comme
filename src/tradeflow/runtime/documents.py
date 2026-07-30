"""Encrypted, tenant-scoped trade-document intake and deterministic checks."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePath
from typing import Any, Callable, Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_PAGES = 100
ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
ACTIVE_CONTENT_MARKERS = (
    b"/javascript",
    b"/launch",
    b"/embeddedfile",
    b"<script",
    b"powershell",
    b"cmd.exe",
)
CONFIRMABLE_FIELDS = frozenset(
    {
        "document_number",
        "currency",
        "amount",
        "issue_date",
        "shipment_date",
        "payment_date",
        "expiry_date",
        "applicant",
        "beneficiary",
        "goods_description",
        "port_of_loading",
        "port_of_discharge",
    }
)
COMPARABLE_FIELDS = frozenset(
    {
        "currency",
        "amount",
        "shipment_date",
        "payment_date",
        "beneficiary",
        "goods_description",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_documents (
    document_id      TEXT PRIMARY KEY,
    account_id       TEXT NOT NULL,
    case_id          TEXT NOT NULL,
    filename         TEXT NOT NULL,
    content_type     TEXT NOT NULL,
    byte_size        INTEGER NOT NULL,
    content_hash     TEXT NOT NULL,
    encrypted_path   TEXT NOT NULL,
    nonce            TEXT NOT NULL,
    document_type    TEXT NOT NULL,
    extraction_state TEXT NOT NULL,
    extraction       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(account_id, case_id, content_hash)
);
CREATE INDEX IF NOT EXISTS trade_documents_tenant_case
    ON trade_documents(account_id, case_id, created_at);
"""


class DocumentValidationError(ValueError):
    """The uploaded bytes are unsafe, unsupported, or internally inconsistent."""


class ClamAvScanner:
    """Invoke an administrator-provided clamscan binary without a shell."""

    def __init__(self, executable: Path | str) -> None:
        self.executable = Path(executable)
        if not self.executable.is_file():
            raise ValueError("clamscan executable does not exist")

    def scan(self, content: bytes, filename: str) -> None:
        suffix = Path(filename).suffix
        with tempfile.TemporaryDirectory(prefix="tradeflow-scan-") as directory:
            target = Path(directory) / f"upload{suffix}"
            target.write_bytes(content)
            completed = subprocess.run(
                [
                    str(self.executable),
                    "--no-summary",
                    "--infected",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        if completed.returncode == 1:
            raise DocumentValidationError("malware scanner rejected the document")
        if completed.returncode != 0:
            raise DocumentValidationError("malware scanner could not verify the document")


def decode_upload(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise DocumentValidationError("document content is required")
    if len(encoded) > ((MAX_DOCUMENT_BYTES + 2) // 3) * 4 + 8:
        raise DocumentValidationError("document exceeds the 10 MiB limit")
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise DocumentValidationError("document content must be base64") from exc
    if not content:
        raise DocumentValidationError("empty documents are not accepted")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentValidationError("document exceeds the 10 MiB limit")
    return content


def _validate_envelope(filename: str, content_type: str, content: bytes) -> str:
    if (
        not filename
        or len(filename) > 180
        or PurePath(filename).name != filename
        or "\x00" in filename
    ):
        raise DocumentValidationError("filename must be a safe basename")
    extension = Path(filename).suffix.lower()
    expected = ALLOWED_TYPES.get(extension)
    if expected is None:
        raise DocumentValidationError("unsupported document extension")
    if content_type != expected:
        raise DocumentValidationError("content type does not match the extension")
    if expected == "application/pdf" and not content.startswith(b"%PDF-"):
        raise DocumentValidationError("PDF signature is missing")
    if expected == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise DocumentValidationError("PNG signature is missing")
    if expected == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
        raise DocumentValidationError("JPEG signature is missing")
    if content.startswith(b"MZ"):
        raise DocumentValidationError("executable content is forbidden")
    lowered = content.lower()
    marker = next((item for item in ACTIVE_CONTENT_MARKERS if item in lowered), None)
    if marker is not None:
        raise DocumentValidationError(
            f"active or executable content marker is forbidden: {marker.decode('ascii')}"
        )
    return expected


def _text_from_document(
    content_type: str,
    content: bytes,
    ocr: Callable[[Any], str] | None = None,
) -> tuple[str, str]:
    if content_type == "text/plain":
        try:
            return content.decode("utf-8"), "extracted"
        except UnicodeDecodeError as exc:
            raise DocumentValidationError("text documents must be UTF-8") from exc
    if content_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise DocumentValidationError("encrypted PDFs require prior decryption")
            if len(reader.pages) > MAX_DOCUMENT_PAGES:
                raise DocumentValidationError("PDF exceeds the 100-page limit")
            text = "\n".join(
                f"[page {index}] {page.extract_text() or ''}"
                for index, page in enumerate(reader.pages, start=1)
            ).strip()
        except DocumentValidationError:
            raise
        except Exception as exc:
            raise DocumentValidationError("PDF structure could not be parsed") from exc
        return (text, "extracted") if text else ("", "needs_ocr")

    try:
        from PIL import Image
        image = Image.open(io.BytesIO(content))
        image.verify()
        image = Image.open(io.BytesIO(content))
        if ocr is None:
            import pytesseract

            configured = os.environ.get("TRADEFLOW_TESSERACT_CMD")
            if configured:
                pytesseract.pytesseract.tesseract_cmd = configured
            text = pytesseract.image_to_string(image, lang="eng+kor").strip()
        else:
            text = ocr(image).strip()
    except Exception:
        return "", "needs_ocr"
    return (text, "extracted") if text else ("", "needs_ocr")


DOCUMENT_CLASSES = (
    ("letter_of_credit", ("letter of credit", "documentary credit", "신용장")),
    ("commercial_invoice", ("commercial invoice", "상업송장", "invoice no")),
    ("packing_list", ("packing list", "포장명세서")),
    ("bill_of_lading", ("bill of lading", "선하증권", "b/l no")),
    ("purchase_order", ("purchase order", "구매주문", "p/o no")),
    ("contract", ("sales contract", "purchase contract", "매매계약서", "계약서")),
    ("customs_declaration", ("customs declaration", "수출신고", "수입신고")),
    ("application_form", ("application form", "신청서")),
)


def _classify(text: str) -> tuple[str, float]:
    lowered = text.lower()
    for document_type, markers in DOCUMENT_CLASSES:
        if any(marker in lowered for marker in markers):
            return document_type, 0.98
    return "unknown", 0.0


FIELD_PATTERNS = {
    "document_number": re.compile(
        r"(?:invoice|l/?c|credit|contract|p/?o|b/?l)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9./_-]*)",
        re.IGNORECASE,
    ),
    "currency_amount": re.compile(
        r"(?:amount|total|금액)\s*[:\-]?\s*(?:(USD|KRW|EUR|JPY|CNY)\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(USD|KRW|EUR|JPY|CNY)?",
        re.IGNORECASE,
    ),
    "issue_date": re.compile(
        r"(?:issue date|invoice date|date of issue|발행일)\s*[:\-]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        re.IGNORECASE,
    ),
    "shipment_date": re.compile(
        r"(?:shipment date|date of shipment|선적일)\s*[:\-]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        re.IGNORECASE,
    ),
    "payment_date": re.compile(
        r"(?:payment date|due date|결제일)\s*[:\-]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        re.IGNORECASE,
    ),
    "expiry_date": re.compile(
        r"(?:expiry date|date of expiry|유효기일)\s*[:\-]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})",
        re.IGNORECASE,
    ),
    "applicant": re.compile(
        r"(?:applicant|buyer|매수인)\s*[:\-]\s*(.+)", re.IGNORECASE
    ),
    "beneficiary": re.compile(
        r"(?:beneficiary|seller|수익자|매도인)\s*[:\-]\s*(.+)", re.IGNORECASE
    ),
    "goods_description": re.compile(
        r"(?:description of goods|goods|품명)\s*[:\-]\s*(.+)", re.IGNORECASE
    ),
    "port_of_loading": re.compile(
        r"(?:port of loading|선적항)\s*[:\-]\s*(.+)", re.IGNORECASE
    ),
    "port_of_discharge": re.compile(
        r"(?:port of discharge|양륙항)\s*[:\-]\s*(.+)", re.IGNORECASE
    ),
}


def _date_value(value: str) -> str:
    return value.replace("/", "-").replace(".", "-")


def _field(
    name: str,
    raw: str,
    normalized: str,
    *,
    page: int | None,
    line: int,
    start: int,
    end: int,
    confidence: float = 0.96,
) -> dict[str, Any]:
    return {
        "field_name": name,
        "extracted_value": raw.strip(),
        "normalized_value": normalized.strip(),
        "confidence": confidence,
        "location": {
            "page": page,
            "line": line,
            "start": start,
            "end": end,
        },
        "confirmed": False,
        "confirmed_value": None,
        "confirmed_by": None,
        "confirmed_at": None,
    }


def _extract_fields(text: str) -> list[dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    current_page: int | None = None
    for line_number, original in enumerate(text.splitlines(), start=1):
        page_match = re.match(r"\[page (\d+)\]\s*", original)
        line = original
        if page_match:
            current_page = int(page_match.group(1))
            line = original[page_match.end():]
        for name, pattern in FIELD_PATTERNS.items():
            match = pattern.search(line)
            if not match:
                continue
            if name == "currency_amount":
                currency = (match.group(1) or match.group(3) or "").upper()
                amount = match.group(2).replace(",", "")
                if currency and "currency" not in fields:
                    fields["currency"] = _field(
                        "currency",
                        currency,
                        currency,
                        page=current_page,
                        line=line_number,
                        start=match.start(),
                        end=match.end(),
                    )
                if "amount" not in fields:
                    fields["amount"] = _field(
                        "amount",
                        match.group(2),
                        str(Decimal(amount)),
                        page=current_page,
                        line=line_number,
                        start=match.start(),
                        end=match.end(),
                    )
                continue
            if name in fields:
                continue
            raw = match.group(1).strip()
            normalized = (
                _date_value(raw)
                if name.endswith("_date")
                else re.sub(r"\s+", " ", raw).strip()
            )
            fields[name] = _field(
                name,
                raw,
                normalized,
                page=current_page,
                line=line_number,
                start=match.start(1),
                end=match.end(1),
            )
    return list(fields.values())


def inspect_and_extract(
    *,
    filename: str,
    content_type: str,
    content: bytes,
    ocr: Callable[[Any], str] | None = None,
) -> dict[str, Any]:
    verified_type = _validate_envelope(filename, content_type, content)
    text, state = _text_from_document(verified_type, content, ocr)
    document_type, classification_confidence = _classify(text)
    return {
        "document_type": document_type,
        "classification_confidence": classification_confidence,
        "extraction_state": state,
        "extractor_version": "trade-document-deterministic.v1",
        "fields": _extract_fields(text),
        "issues": (
            ["텍스트를 찾지 못했습니다. 승인된 OCR 환경에서 다시 추출해야 합니다."]
            if state == "needs_ocr"
            else []
        ),
    }


class TradeDocumentStore:
    """Store encrypted originals and reviewable extractions by tenant."""

    def __init__(
        self,
        db_path: Path | str,
        blob_root: Path | str,
        encryption_key: bytes,
        malware_scanner: ClamAvScanner | None = None,
    ) -> None:
        if len(encryption_key) != 32:
            raise ValueError("document encryption key must contain 32 bytes")
        self.db_path = Path(db_path)
        self.blob_root = Path(blob_root)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._cipher = AESGCM(encryption_key)
        self.malware_scanner = malware_scanner
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(
        self,
        *,
        account_id: str,
        case_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if self.malware_scanner:
            self.malware_scanner.scan(content, filename)
        if not case_id.strip() or len(case_id) > 120:
            raise DocumentValidationError("case_id is required")
        extraction = inspect_and_extract(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        with self._connect() as db:
            existing = db.execute(
                "SELECT document_id FROM trade_documents"
                " WHERE account_id = ? AND case_id = ? AND content_hash = ?",
                (account_id, case_id, digest),
            ).fetchone()
        if existing:
            return self.read(account_id, existing["document_id"])

        document_id = f"DOC-{secrets.token_hex(12)}"
        nonce = secrets.token_bytes(12)
        associated = f"{account_id}:{case_id}:{document_id}".encode("utf-8")
        encrypted = self._cipher.encrypt(nonce, content, associated)
        blob_path = self.blob_root / f"{document_id}.bin"
        blob_path.write_bytes(encrypted)
        created_at = (now or datetime.now(UTC)).isoformat()
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO trade_documents"
                    " (document_id, account_id, case_id, filename, content_type,"
                    " byte_size, content_hash, encrypted_path, nonce,"
                    " document_type, extraction_state, extraction, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        document_id,
                        account_id,
                        case_id,
                        filename,
                        content_type,
                        len(content),
                        digest,
                        str(blob_path),
                        base64.b64encode(nonce).decode("ascii"),
                        extraction["document_type"],
                        extraction["extraction_state"],
                        json.dumps(extraction, ensure_ascii=False),
                        created_at,
                    ),
                )
        except Exception:
            blob_path.unlink(missing_ok=True)
            raise
        return self.read(account_id, document_id)

    def read(self, account_id: str, document_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT document_id, case_id, filename, content_type, byte_size,"
                " content_hash, document_type, extraction_state, extraction,"
                " created_at FROM trade_documents"
                " WHERE account_id = ? AND document_id = ?",
                (account_id, document_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "document_id": row["document_id"],
            "case_id": row["case_id"],
            "filename": row["filename"],
            "content_type": row["content_type"],
            "byte_size": row["byte_size"],
            "content_hash": row["content_hash"],
            "document_type": row["document_type"],
            "extraction_state": row["extraction_state"],
            "extraction": json.loads(row["extraction"]),
            "created_at": row["created_at"],
        }

    def confirm(
        self,
        account_id: str,
        document_id: str,
        values: Mapping[str, str],
        *,
        confirmed_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        unknown = set(values) - CONFIRMABLE_FIELDS
        if unknown:
            raise DocumentValidationError(
                "unsupported confirmation fields: " + ", ".join(sorted(unknown))
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT extraction FROM trade_documents"
                " WHERE account_id = ? AND document_id = ?",
                (account_id, document_id),
            ).fetchone()
            if row is None:
                return None
            extraction = json.loads(row["extraction"])
            fields = {
                item["field_name"]: item
                for item in extraction.get("fields", [])
            }
            confirmed_at = (now or datetime.now(UTC)).isoformat()
            for name, value in values.items():
                normalized = _normalize(name, value)
                item = fields.get(name)
                if item is None:
                    item = _field(
                        name,
                        "",
                        "",
                        page=None,
                        line=0,
                        start=0,
                        end=0,
                        confidence=0,
                    )
                    extraction["fields"].append(item)
                    fields[name] = item
                item.update(
                    {
                        "confirmed": True,
                        "confirmed_value": normalized,
                        "confirmed_by": confirmed_by,
                        "confirmed_at": confirmed_at,
                    }
                )
            db.execute(
                "UPDATE trade_documents SET extraction = ?"
                " WHERE account_id = ? AND document_id = ?",
                (
                    json.dumps(extraction, ensure_ascii=False),
                    account_id,
                    document_id,
                ),
            )
        return self.read(account_id, document_id)

    def list_case(self, account_id: str, case_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT document_id FROM trade_documents"
                " WHERE account_id = ? AND case_id = ? ORDER BY created_at",
                (account_id, case_id),
            ).fetchall()
        return tuple(
            document
            for row in rows
            if (document := self.read(account_id, row["document_id"])) is not None
        )

    def check_case(
        self,
        account_id: str,
        case_id: str,
        expected_fields: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        documents = self.list_case(account_id, case_id)
        expected = {
            name: _normalize(name, value)
            for name, value in (expected_fields or {}).items()
            if name in COMPARABLE_FIELDS
        }
        findings: list[dict[str, Any]] = []
        observed: dict[str, list[tuple[str, str]]] = {}
        for document in documents:
            fields = {
                item["field_name"]: (
                    item["confirmed_value"]
                    if item.get("confirmed")
                    else item.get("normalized_value")
                )
                for item in document["extraction"].get("fields", [])
            }
            for name in COMPARABLE_FIELDS:
                value = fields.get(name)
                if value not in (None, ""):
                    observed.setdefault(name, []).append(
                        (document["document_id"], str(value))
                    )
            if document["document_type"] == "letter_of_credit":
                required = {
                    "document_number",
                    "currency",
                    "amount",
                    "expiry_date",
                    "applicant",
                    "beneficiary",
                }
                for name in sorted(required - set(fields)):
                    findings.append(
                        {
                            "kind": "missing_lc_field",
                            "severity": "review_required",
                            "field": name,
                            "document_ids": [document["document_id"]],
                            "reason": "신용장 필수 조건을 확인할 수 없습니다.",
                        }
                    )
                shipment = fields.get("shipment_date")
                expiry = fields.get("expiry_date")
                if shipment and expiry and shipment > expiry:
                    findings.append(
                        {
                            "kind": "invalid_lc_date_order",
                            "severity": "review_required",
                            "field": "shipment_date",
                            "document_ids": [document["document_id"]],
                            "reason": "선적일이 신용장 유효기일보다 늦습니다.",
                        }
                    )

        for name, values in observed.items():
            unique = {value for _, value in values}
            if len(unique) > 1:
                findings.append(
                    {
                        "kind": "cross_document_mismatch",
                        "severity": "review_required",
                        "field": name,
                        "document_ids": [document_id for document_id, _ in values],
                        "observed": [
                            {"document_id": document_id, "value": value}
                            for document_id, value in values
                        ],
                        "reason": "문서 간 값이 일치하지 않습니다.",
                    }
                )
            if name in expected and any(value != expected[name] for _, value in values):
                findings.append(
                    {
                        "kind": "trade_document_mismatch",
                        "severity": "review_required",
                        "field": name,
                        "document_ids": [document_id for document_id, _ in values],
                        "expected": expected[name],
                        "observed": [
                            {"document_id": document_id, "value": value}
                            for document_id, value in values
                        ],
                        "reason": "확정 거래 정보와 문서 값이 일치하지 않습니다.",
                    }
                )
        return {
            "case_id": case_id,
            "document_count": len(documents),
            "document_types": [item["document_type"] for item in documents],
            "findings": findings,
            "review_required": bool(findings),
        }


POSTGRES_DOCUMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_documents (
    document_id      TEXT PRIMARY KEY,
    organization_id  TEXT NOT NULL,
    case_id          TEXT NOT NULL,
    filename         TEXT NOT NULL,
    content_type     TEXT NOT NULL,
    byte_size        INTEGER NOT NULL,
    content_hash     TEXT NOT NULL,
    encrypted_path   TEXT NOT NULL,
    nonce            TEXT NOT NULL,
    document_type    TEXT NOT NULL,
    extraction_state TEXT NOT NULL,
    extraction       JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    UNIQUE(organization_id, case_id, content_hash)
);
CREATE INDEX IF NOT EXISTS trade_documents_tenant_case
    ON trade_documents(organization_id, case_id, created_at);
"""


class PostgresTradeDocumentStore(TradeDocumentStore):
    """PostgreSQL metadata store with encrypted originals in a private volume."""

    def __init__(
        self,
        database_url: str,
        blob_root: Path | str,
        encryption_key: bytes,
        malware_scanner: ClamAvScanner | None = None,
    ) -> None:
        if len(encryption_key) != 32:
            raise ValueError("document encryption key must contain 32 bytes")
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("a PostgreSQL database URL is required")
        self.database_url = database_url
        self.blob_root = Path(blob_root)
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self._cipher = AESGCM(encryption_key)
        self.malware_scanner = malware_scanner
        with self._connect() as db:
            db.execute(POSTGRES_DOCUMENT_SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.database_url, row_factory=dict_row) as db:
            yield db

    def save(
        self,
        *,
        account_id: str,
        case_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        if self.malware_scanner:
            self.malware_scanner.scan(content, filename)
        if not case_id.strip() or len(case_id) > 120:
            raise DocumentValidationError("case_id is required")
        extraction = inspect_and_extract(
            filename=filename,
            content_type=content_type,
            content=content,
        )
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        with self._connect() as db:
            existing = db.execute(
                "SELECT document_id FROM trade_documents"
                " WHERE organization_id = %s AND case_id = %s"
                " AND content_hash = %s",
                (account_id, case_id, digest),
            ).fetchone()
        if existing:
            return self.read(account_id, existing["document_id"])

        document_id = f"DOC-{secrets.token_hex(12)}"
        nonce = secrets.token_bytes(12)
        associated = f"{account_id}:{case_id}:{document_id}".encode()
        blob_path = self.blob_root / f"{document_id}.bin"
        blob_path.write_bytes(self._cipher.encrypt(nonce, content, associated))
        created_at = now or datetime.now(UTC)
        try:
            with self._connect() as db:
                inserted = db.execute(
                    "INSERT INTO trade_documents"
                    " (document_id, organization_id, case_id, filename,"
                    " content_type, byte_size, content_hash, encrypted_path,"
                    " nonce, document_type, extraction_state, extraction,"
                    " created_at) VALUES"
                    " (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (organization_id, case_id, content_hash)"
                    " DO NOTHING RETURNING document_id",
                    (
                        document_id,
                        account_id,
                        case_id,
                        filename,
                        content_type,
                        len(content),
                        digest,
                        str(blob_path),
                        base64.b64encode(nonce).decode(),
                        extraction["document_type"],
                        extraction["extraction_state"],
                        Jsonb(extraction),
                        created_at,
                    ),
                ).fetchone()
                if inserted is None:
                    existing = db.execute(
                        "SELECT document_id FROM trade_documents"
                        " WHERE organization_id = %s AND case_id = %s"
                        " AND content_hash = %s",
                        (account_id, case_id, digest),
                    ).fetchone()
                    blob_path.unlink(missing_ok=True)
                    return self.read(account_id, existing["document_id"])
        except Exception:
            blob_path.unlink(missing_ok=True)
            raise
        return self.read(account_id, document_id)

    def read(self, account_id: str, document_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT document_id, case_id, filename, content_type, byte_size,"
                " content_hash, document_type, extraction_state, extraction,"
                " created_at FROM trade_documents"
                " WHERE organization_id = %s AND document_id = %s",
                (account_id, document_id),
            ).fetchone()
        if row is None:
            return None
        return {
            **row,
            "created_at": row["created_at"].isoformat(),
            "extraction": (
                row["extraction"]
                if isinstance(row["extraction"], dict)
                else json.loads(row["extraction"])
            ),
        }

    def confirm(
        self,
        account_id: str,
        document_id: str,
        values: Mapping[str, str],
        *,
        confirmed_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        from psycopg.types.json import Jsonb

        unknown = set(values) - CONFIRMABLE_FIELDS
        if unknown:
            raise DocumentValidationError(
                "unsupported confirmation fields: " + ", ".join(sorted(unknown))
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT extraction FROM trade_documents"
                " WHERE organization_id = %s AND document_id = %s FOR UPDATE",
                (account_id, document_id),
            ).fetchone()
            if row is None:
                return None
            extraction = (
                row["extraction"]
                if isinstance(row["extraction"], dict)
                else json.loads(row["extraction"])
            )
            fields = {
                item["field_name"]: item
                for item in extraction.get("fields", [])
            }
            confirmed_at = (now or datetime.now(UTC)).isoformat()
            for name, value in values.items():
                normalized = _normalize(name, value)
                item = fields.get(name)
                if item is None:
                    item = _field(
                        name,
                        "",
                        "",
                        page=None,
                        line=0,
                        start=0,
                        end=0,
                        confidence=0,
                    )
                    extraction["fields"].append(item)
                    fields[name] = item
                item.update(
                    {
                        "confirmed": True,
                        "confirmed_value": normalized,
                        "confirmed_by": confirmed_by,
                        "confirmed_at": confirmed_at,
                    }
                )
            db.execute(
                "UPDATE trade_documents SET extraction = %s"
                " WHERE organization_id = %s AND document_id = %s",
                (Jsonb(extraction), account_id, document_id),
            )
        return self.read(account_id, document_id)

    def list_case(self, account_id: str, case_id: str) -> tuple[dict[str, Any], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT document_id FROM trade_documents"
                " WHERE organization_id = %s AND case_id = %s"
                " ORDER BY created_at",
                (account_id, case_id),
            ).fetchall()
        return tuple(
            document
            for row in rows
            if (document := self.read(account_id, row["document_id"])) is not None
        )


def _normalize(name: str, value: Any) -> str:
    text = str(value).strip()
    if not text or len(text) > 500 or any(ord(character) < 32 for character in text):
        raise DocumentValidationError(f"{name}: invalid confirmation value")
    if name == "currency":
        normalized = text.upper()
        if normalized not in {"USD", "KRW", "EUR", "JPY", "CNY"}:
            raise DocumentValidationError("currency is unsupported")
        return normalized
    if name == "amount":
        try:
            number = Decimal(text.replace(",", ""))
        except InvalidOperation as exc:
            raise DocumentValidationError("amount must be numeric") from exc
        if not number.is_finite() or number < 0:
            raise DocumentValidationError("amount must be a non-negative finite value")
        return str(number)
    if name.endswith("_date"):
        normalized = _date_value(text)
        try:
            datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise DocumentValidationError(f"{name}: ISO date is required") from exc
        return normalized
    return re.sub(r"\s+", " ", text)
