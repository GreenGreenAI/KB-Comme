"""HTTP surface for the TradeFlow web application.

The conversation is deliberately stateless: the browser holds what has been said
so far and resends it. Keeping it on the server would add expiry, eviction and a
second source of truth for what the user has told us, none of which this product
needs — the intake loop is short and the client already has to render everything
it knows.

The session is the one thing that is not stateless, and for the opposite reason:
it says who the user is, and a claim about identity that the client can edit is
not a claim at all. It carries no conversation — only which account is signed
in, so the company facts §5.4 reads come from an account instead of from a
request body that could say anything.

Signing in is not required. An anonymous visitor states company facts in the
request as before; a signed-in one has them supplied by their account, and the
request cannot override them.

This module only moves data. Deciding what to ask lives in the intake agent,
and deciding what to run lives in the orchestrator.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradeflow.agent.intake import intake
from tradeflow.runtime.accounts import SESSION_DAYS, Account, AccountStore
from tradeflow.runtime.documents import (
    ClamAvScanner,
    DocumentValidationError,
    PostgresTradeDocumentStore,
    TradeDocumentStore,
    decode_upload,
)
from tradeflow.runtime.postgres_accounts import PostgresAccountStore
from tradeflow.runtime.synthesis import Synthesizer, figures
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.orchestrator import DECLARED_COMPANY_FIELDS
from tradeflow.agent.response import build_response
from tradeflow.domain.models import CompanyProfile
from tradeflow.knowledge.compliance_declarations import (
    ComplianceGatewayDeclaration,
)
from tradeflow.tools.utterance import (
    AMBIGUOUS,
    APPEND,
    place_utterance,
    read_utterance,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_ROOT = REPO_ROOT / "data" / "snapshots"
FRONTEND_DIST = REPO_ROOT / "web" / "frontend" / "dist"
ACCOUNT_DB = Path(os.environ.get("TRADEFLOW_ACCOUNT_DB", REPO_ROOT / "data" / "accounts.db"))
DATABASE_URL = os.environ.get("TRADEFLOW_DATABASE_URL")
DOCUMENT_ROOT = Path(
    os.environ.get("TRADEFLOW_DOCUMENT_ROOT", REPO_ROOT / "data" / "documents")
)
CLAMSCAN_PATH = os.environ.get("TRADEFLOW_CLAMSCAN_PATH")

SESSION_COOKIE = "tradeflow_session"

#: Annotated rather than `= Cookie(default=None)`, so the real default is None.
#: With the old form the tests that call these endpoints as plain functions —
#: which is how every other endpoint here is tested — received the `Cookie`
#: marker object itself as the token.
SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]

app = FastAPI(title="TradeFlow", version="0.1.0")
if os.environ.get("TRADEFLOW_ENV") == "production" and not DATABASE_URL:
    raise RuntimeError(
        "TRADEFLOW_DATABASE_URL is required in production; "
        "SQLite is development-only"
    )
if os.environ.get("TRADEFLOW_ENV") == "production" and not CLAMSCAN_PATH:
    raise RuntimeError("TRADEFLOW_CLAMSCAN_PATH is required in production")
if (
    os.environ.get("TRADEFLOW_ENV") == "production"
    and not os.environ.get("TRADEFLOW_TESSERACT_CMD")
):
    raise RuntimeError("TRADEFLOW_TESSERACT_CMD is required in production")
accounts = (
    PostgresAccountStore(DATABASE_URL)
    if DATABASE_URL
    else AccountStore(ACCOUNT_DB)
)
malware_scanner = ClamAvScanner(CLAMSCAN_PATH) if CLAMSCAN_PATH else None


def _document_encryption_key() -> bytes:
    configured = os.environ.get("TRADEFLOW_DOCUMENT_KEY")
    if configured:
        try:
            key = base64.b64decode(configured, validate=True)
        except Exception as exc:
            raise RuntimeError(
                "TRADEFLOW_DOCUMENT_KEY must be base64-encoded"
            ) from exc
        if len(key) != 32:
            raise RuntimeError("TRADEFLOW_DOCUMENT_KEY must decode to 32 bytes")
        return key
    if os.environ.get("TRADEFLOW_ENV", "development") == "production":
        raise RuntimeError(
            "TRADEFLOW_DOCUMENT_KEY is required in production"
        )
    key_path = REPO_ROOT / "data" / ".document-key"
    if key_path.exists():
        key = key_path.read_bytes()
    else:
        key = secrets.token_bytes(32)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
        key_path.chmod(0o600)
    if len(key) != 32:
        raise RuntimeError("local document key is invalid")
    return key


document_store = (
    PostgresTradeDocumentStore(
        DATABASE_URL,
        DOCUMENT_ROOT,
        _document_encryption_key(),
        malware_scanner,
    )
    if DATABASE_URL
    else TradeDocumentStore(
        ACCOUNT_DB,
        DOCUMENT_ROOT,
        _document_encryption_key(),
        malware_scanner,
    )
)

ALLOWED_ORIGINS = frozenset(
    item.strip()
    for item in os.environ.get(
        "TRADEFLOW_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if item.strip()
)


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and origin
        and origin not in ALLOWED_ORIGINS
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": {"reason": "허용되지 않은 요청 출처입니다"}},
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response

#: §4.2[9]. Constructed whether or not a key is present — without one it simply
#: declines, and the screen writes its own sentence.
synthesizer = Synthesizer()
logger = logging.getLogger("tradeflow.synthesis")


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileFactsRequest(BaseModel):
    facts: dict[str, Any]


class DocumentUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=1, max_length=100)
    content_base64: str = Field(min_length=1)


class DocumentConfirmationRequest(BaseModel):
    fields: dict[str, str]


class DocumentCheckRequest(BaseModel):
    expected_fields: dict[str, str] = Field(default_factory=dict)


def _signed_in(token: str | None) -> Account | None:
    return accounts.read_session(token)


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    """Exchange a password for a session, or say no without saying why.

    One message for both failures. "그런 계정이 없습니다" would answer a
    question nobody asked — whether a given company banks here — to anyone
    willing to type addresses into the form.
    """
    account = accounts.authenticate(body.email, body.password)
    if account is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "이메일 또는 비밀번호가 올바르지 않습니다"},
        )
    token = accounts.open_session(account)
    accounts.append_audit(
        account,
        action="auth.login",
        target_type="session",
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        # The browser may hold it but script may not read it: an XSS that can
        # run in this page still cannot walk away with the session.
        httponly=True,
        samesite="lax",
        # Off for local http development, on wherever this is served over TLS.
        secure=bool(os.environ.get("TRADEFLOW_SECURE_COOKIE")),
        path="/",
    )
    return {"account": _account_view(account)}


@app.post("/api/auth/logout")
def logout(
    response: Response,
    session: SessionCookie = None,
) -> dict[str, Any]:
    """End it on the server, then drop the cookie.

    Clearing the cookie alone would leave a token that still works for anyone
    who kept a copy of it.
    """
    account = _signed_in(session)
    if account:
        accounts.append_audit(
            account,
            action="auth.logout",
            target_type="session",
        )
    accounts.close_session(session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"account": None}


@app.get("/api/auth/me")
def me(session: SessionCookie = None) -> dict[str, Any]:
    """Who the server thinks you are.

    The screen asks rather than remembering, so being signed in is something
    the server says and not something the client decides about itself.
    """
    account = _signed_in(session)
    return {"account": _account_view(account) if account else None}


def _account_view(account: Account) -> dict[str, Any]:
    """What the screen may show — the same facts the analysis will receive.

    Nothing is summarised or prettified on the way out. The account menu used
    to state "중소기업 · 제조업" from a hardcoded string while the analysis ran
    for a nameless company; sending the facts themselves is what keeps the two
    from drifting apart again.
    """
    return {
        "account_id": account.account_id,
        "organization_id": account.organization_id,
        "role": account.role,
        "email": account.email,
        "company_name": account.company_name,
        "facts": account.facts,
    }


class CaseInput(BaseModel):
    """One trade, as far as the user has described it."""

    direction: str | None = None
    amount: str | None = None
    expected_payment_date: str | None = None
    currency: str | None = None
    payment_method: str | None = None
    country: str | None = None
    counterparty_id: str | None = None
    expected_shipment_date: str | None = None
    advance_payment_ratio: str | None = None
    contract_date: str | None = None
    case_facts: dict[str, Any] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    cases: list[CaseInput] = Field(default_factory=list)
    utterance: str | None = None
    company_name: str = "미입력 기업"
    is_sme: bool | None = None
    company_facts: dict[str, Any] = Field(default_factory=dict)
    compliance_declarations: list["ComplianceGatewayInput"] = Field(
        default_factory=list
    )
    opening_balance_usd: str | None = None
    baseline_profit: str | None = None
    profit_floor: str | None = None
    as_of: str | None = None
    #: Set only when the user has already answered "새 거래인가, 수정인가".
    #: Left unset, an ambiguous sentence comes back as a question instead of
    #: being resolved by a guess.
    placement: Literal["append", "merge"] | None = None


class ComplianceGatewayInput(BaseModel):
    """A confirmed company statement about one trade's payment structure."""

    case_index: int = Field(default=0, ge=0)
    declared_by_role: str = "company_user"
    confirmed: Literal[True]
    is_netting: bool | None = None
    is_third_party: bool | None = None
    uses_mutual_account: bool | None = None
    uses_foreign_exchange_bank: bool | None = None


AnalyzeRequest.model_rebuild()


ANONYMOUS_COMPANY_FACTS = frozenset(
    (*DECLARED_COMPANY_FIELDS, "company.is_domestic")
)
CASE_FACT_INPUT_FIELDS = frozenset(
    {
        "trade.payment_term_days",
        "financing.purpose",
    }
)


def _require_account(session: str | None) -> Account:
    account = _signed_in(session)
    if account is None:
        raise HTTPException(
            status_code=401,
            detail={"reason": "로그인이 필요합니다"},
        )
    return account


def _require_permission(
    account: Account,
    permission: str,
    *,
    target_type: str,
    target_id: str | None = None,
) -> None:
    if account.can(permission):
        return
    accounts.append_audit(
        account,
        action=f"authorization.{permission}",
        target_type=target_type,
        target_id=target_id,
        outcome="denied",
    )
    raise HTTPException(
        status_code=403,
        detail={"reason": "이 작업을 수행할 권한이 없습니다"},
    )


def _validate_company_facts(facts: dict[str, Any]) -> None:
    unknown = set(facts) - ANONYMOUS_COMPANY_FACTS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={
                "field": "company_facts",
                "reason": "지원하지 않는 기업 사실: " + ", ".join(sorted(unknown)),
            },
        )


@app.patch("/api/auth/profile")
def update_profile(
    body: ProfileFactsRequest,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(account, "profile:write", target_type="profile")
    _validate_company_facts(body.facts)
    updated = accounts.update_facts(account, body.facts)
    accounts.append_audit(
        updated,
        action="profile.update",
        target_type="profile",
        target_id=updated.organization_id,
        details={"fields": sorted(body.facts)},
    )
    return {"account": _account_view(updated)}


@app.get("/api/analyses")
def analysis_history(
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(account, "analysis:read", target_type="analysis")
    return {"analyses": list(accounts.list_analyses(account))}


@app.get("/api/analyses/{run_id}")
def saved_analysis(
    run_id: str,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(
        account,
        "analysis:read",
        target_type="analysis",
        target_id=run_id,
    )
    stored = accounts.read_analysis(account, run_id)
    if stored is None:
        raise HTTPException(status_code=404, detail={"reason": "분석을 찾을 수 없습니다"})
    accounts.append_audit(
        account,
        action="analysis.read",
        target_type="analysis",
        target_id=run_id,
    )
    return stored


def _document_validation_error(exc: DocumentValidationError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"field": "document", "reason": str(exc)},
    )


@app.post("/api/trade-cases/{case_id}/documents")
def upload_document(
    case_id: str,
    body: DocumentUploadRequest,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(
        account,
        "document:upload",
        target_type="trade_case",
        target_id=case_id,
    )
    try:
        content = decode_upload(body.content_base64)
        document = document_store.save(
            account_id=account.organization_id,
            case_id=case_id,
            filename=body.filename,
            content_type=body.content_type,
            content=content,
        )
    except DocumentValidationError as exc:
        raise _document_validation_error(exc) from exc
    accounts.append_audit(
        account,
        action="document.upload",
        target_type="document",
        target_id=document["document_id"],
        details={
            "case_id": case_id,
            "content_hash": document["content_hash"],
            "document_type": document["document_type"],
        },
    )
    return {"document": document}


@app.get("/api/trade-cases/{case_id}/documents")
def list_trade_documents(
    case_id: str,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(
        account,
        "document:read",
        target_type="trade_case",
        target_id=case_id,
    )
    documents = list(
        document_store.list_case(account.organization_id, case_id)
    )
    accounts.append_audit(
        account,
        action="document.list",
        target_type="trade_case",
        target_id=case_id,
        details={"document_count": len(documents)},
    )
    return {
        "documents": documents
    }


@app.get("/api/documents/{document_id}/extraction")
def document_extraction(
    document_id: str,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(
        account,
        "document:read",
        target_type="document",
        target_id=document_id,
    )
    document = document_store.read(account.organization_id, document_id)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "문서를 찾을 수 없습니다"},
        )
    accounts.append_audit(
        account,
        action="document.read",
        target_type="document",
        target_id=document_id,
    )
    return {"document": document}


@app.post("/api/documents/{document_id}/confirm-fields")
def confirm_document_fields(
    document_id: str,
    body: DocumentConfirmationRequest,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(
        account,
        "document:confirm",
        target_type="document",
        target_id=document_id,
    )
    try:
        document = document_store.confirm(
            account.organization_id,
            document_id,
            body.fields,
            confirmed_by=account.email,
        )
    except DocumentValidationError as exc:
        raise _document_validation_error(exc) from exc
    if document is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "문서를 찾을 수 없습니다"},
        )
    accounts.append_audit(
        account,
        action="document.confirm_fields",
        target_type="document",
        target_id=document_id,
        details={"fields": sorted(body.fields)},
    )
    return {"document": document}


@app.post("/api/trade-cases/{case_id}/document-check")
def check_trade_documents(
    case_id: str,
    body: DocumentCheckRequest,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(
        account,
        "document:check",
        target_type="trade_case",
        target_id=case_id,
    )
    try:
        result = document_store.check_case(
            account.organization_id,
            case_id,
            body.expected_fields,
        )
    except DocumentValidationError as exc:
        raise _document_validation_error(exc) from exc
    accounts.append_audit(
        account,
        action="document.check",
        target_type="trade_case",
        target_id=case_id,
        details={
            "document_count": result["document_count"],
            "finding_count": len(result["findings"]),
        },
    )
    return result


@app.get("/api/audit-events")
def audit_events(
    limit: int = 100,
    session: SessionCookie = None,
) -> dict[str, Any]:
    account = _require_account(session)
    _require_permission(account, "audit:read", target_type="audit")
    accounts.append_audit(
        account,
        action="audit.read",
        target_type="audit",
        details={"limit": max(1, min(limit, 500))},
    )
    return {
        "events": list(accounts.list_audit(account, limit=limit)),
        "chain_valid": accounts.verify_audit_chain(account.organization_id),
    }


def _anonymous_profile(request: AnalyzeRequest) -> CompanyProfile:
    _validate_company_facts(request.company_facts)
    return CompanyProfile(
        company_id="COMPANY-ANONYMOUS",
        name=request.company_name,
        is_sme=request.is_sme,
        attributes=dict(request.company_facts),
    )


def _validate_case_facts(cases: list[CaseInput]) -> None:
    unknown = {
        field
        for case in cases
        for field in case.case_facts
        if field not in CASE_FACT_INPUT_FIELDS
    }
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={
                "field": "cases.case_facts",
                "reason": "지원하지 않는 거래 사실: " + ", ".join(sorted(unknown)),
            },
        )


def _declarations(
    request: AnalyzeRequest,
    *,
    company_id: str,
    case_ids: list[str],
    declared_at: datetime,
) -> tuple[ComplianceGatewayDeclaration, ...]:
    declarations: list[ComplianceGatewayDeclaration] = []
    seen: set[int] = set()
    for item in request.compliance_declarations:
        if item.case_index >= len(case_ids):
            raise HTTPException(
                status_code=422,
                detail={
                    "field": "compliance_declarations.case_index",
                    "reason": "존재하지 않는 거래를 참조합니다",
                },
            )
        if item.case_index in seen:
            raise HTTPException(
                status_code=422,
                detail={
                    "field": "compliance_declarations.case_index",
                    "reason": "거래별 활성 선언은 하나만 허용됩니다",
                },
            )
        seen.add(item.case_index)
        declarations.append(
            ComplianceGatewayDeclaration(
                declaration_id=f"WEB-{case_ids[item.case_index]}",
                company_id=company_id,
                case_id=case_ids[item.case_index],
                declared_at=declared_at,
                declared_by_role=item.declared_by_role,
                confirmed=item.confirmed,
                is_netting=item.is_netting,
                is_third_party=item.is_third_party,
                uses_mutual_account=item.uses_mutual_account,
                uses_foreign_exchange_bank=item.uses_foreign_exchange_bank,
            )
        )
    return tuple(declarations)


FIELD_LABELS = {
    "direction": "거래 방향",
    "amount": "금액",
    "expected_payment_date": "결제일",
}


def _placement_question(
    utterance: str,
    heard: dict[str, Any],
    supplied: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ask whether a sentence adds a trade or corrects the current one.

    The sentence restated something the latest trade already says, with a
    different value, and in the same direction. "12월 3일에 15만 달러 수취" after
    an export of 10만 is either a second shipment or a fix to the first, and
    nothing in the words decides it. Answering by rule would either invent a
    trade the company does not have or erase one it does.
    """
    differing = ", ".join(
        FIELD_LABELS.get(field, field)
        for field in place_utterance(heard, supplied).conflicts
    )
    return {
        "status": "needs_placement",
        "understood": heard,
        "utterance": utterance,
        "question": (
            f"방금 말씀하신 내용이 앞의 거래와 {differing}에서 다릅니다. "
            "새로운 거래인가요, 앞 거래를 고치신 건가요?"
        ),
        "options": [
            {"placement": "append", "label": "새 거래로 추가"},
            {"placement": "merge", "label": "앞 거래를 수정"},
        ],
    }


def _money(raw: str | None, field_name: str) -> Decimal | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation:
        raise HTTPException(
            status_code=422,
            detail={"field": field_name, "reason": "유효한 숫자를 입력해 주세요"},
        ) from None
    if not value.is_finite():
        raise HTTPException(
            status_code=422,
            detail={"field": field_name, "reason": "유한한 숫자를 입력해 주세요"},
        )
    return value


def _analysis_date(raw: str | None) -> date:
    if raw is None or not raw.strip():
        return date.today()
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"field": "as_of", "reason": "ISO 날짜를 입력해 주세요"},
        ) from None
    if value > date.today():
        raise HTTPException(
            status_code=422,
            detail={"field": "as_of", "reason": "미래 날짜는 사용할 수 없습니다"},
        )
    return value


@app.post("/api/analyze")
def analyze_endpoint(
    request: AnalyzeRequest,
    session: SessionCookie = None,
) -> dict[str, Any]:
    """Either the questions still blocking an answer, or the answer.

    Company facts come from the account when there is one, and the request
    cannot override them. Letting the body win would put back exactly the gap
    an account was meant to close: a screen showing one company while the
    analysis ran for another. Anonymous callers still state their own facts —
    signing in is not required to get an answer, only to stop repeating
    yourself.
    """
    account = _signed_in(session)
    if account:
        _require_permission(
            account,
            "analysis:write",
            target_type="analysis",
        )
    _validate_case_facts(request.cases)
    as_of = _analysis_date(request.as_of)
    opening_balance = _money(request.opening_balance_usd, "opening_balance_usd")
    baseline_profit = _money(request.baseline_profit, "baseline_profit")
    profit_floor = _money(request.profit_floor, "profit_floor")
    if profit_floor is not None and baseline_profit is None:
        raise HTTPException(
            status_code=422,
            detail={
                "field": "baseline_profit",
                "reason": "목표 손익 하한과 함께 기준 영업이익을 입력해 주세요",
            },
        )
    balances = (
        {"USD": str(opening_balance)}
        if opening_balance is not None
        else None
    )

    supplied = [case.model_dump() for case in request.cases]
    heard: dict[str, Any] = {}
    if request.utterance:
        heard = read_utterance(request.utterance, as_of=as_of)
        if heard:
            action = request.placement or place_utterance(
                heard,
                supplied,
                utterance=request.utterance,
            ).action
            if action == AMBIGUOUS:
                return _placement_question(request.utterance, heard, supplied)
            if action == APPEND:
                supplied = [*supplied, dict(heard)]
            else:
                target = supplied[-1] if supplied else {}
                if request.placement == "merge":
                    # The user explicitly chose to correct the current trade,
                    # so the newly stated values must win.
                    merged = {
                        **{k: v for k, v in target.items() if v},
                        **heard,
                    }
                else:
                    # During ordinary slot filling, values already entered in
                    # the structured form remain authoritative.
                    merged = {
                        **heard,
                        **{k: v for k, v in target.items() if v},
                    }
                supplied = [*supplied[:-1], merged] if supplied else [merged]

    profile = account.profile() if account else _anonymous_profile(request)
    reading = intake(
        supplied,
        company=profile,
        company_name=request.company_name,
        is_sme=request.is_sme,
        opening_balances=balances,
        as_of=as_of,
    )

    if not reading.ready:
        return {
            "status": "needs_input",
            "understood": heard,
            # §4.2[1] in words. `questions` stays — the request panel pairs a
            # field with its own wording, and this one sentence covers all
            # three at once. What is asked for is still decided by the slot
            # reader; only the phrasing comes from the model, and an empty
            # `spoken` leaves the screen listing `questions` as before.
            "spoken": synthesizer.ask_for(
                list(reading.missing),
                understood=heard,
                question=request.utterance,
            ).summary,
            "questions": list(reading.questions),
            # Field and wording paired, so the screen asks for the thing it is
            # quoting the question for.
            "asked": [
                {"field": field, "question": question}
                for field, question in reading.prompts
            ],
            "missing": list(reading.missing),
            "issues": [
                {"field": issue.field, "reason": issue.reason}
                for issue in reading.issues
            ],
        }

    evaluated_at = datetime.now(UTC)
    declarations = _declarations(
        request,
        company_id=reading.program.company.company_id,
        case_ids=[case.case_id for case in reading.program.cases],
        declared_at=evaluated_at,
    )
    analysis = analyze(
        reading.program,
        snapshot_root=SNAPSHOT_ROOT,
        baseline_profit=baseline_profit,
        profit_floor=profit_floor,
        compliance_declarations=declarations,
        utterance=request.utterance,
        as_of=evaluated_at,
    )
    result = build_response(analysis)

    # §4.2[9]: the last step, and the only one a language model touches. It is
    # given the figures the tools produced and nothing else, and what it writes
    # is checked against them before it is used. A refusal — no key, no
    # network, or a sentence that invented a number — leaves `summary` empty
    # and the screen assembles its own sentence, so prose is the only thing
    # that can be lost here.
    written = synthesizer.write(figures(result), question=request.utterance)
    if written.accepted:
        result["summary"] = written.sentence
    elif written.reason:
        logger.info("합성 미채택: %s | %s", written.reason, written.sentence[:120])
    run_id = accounts.save_analysis(account, result) if account else None
    if account and run_id:
        accounts.append_audit(
            account,
            action="analysis.create",
            target_type="analysis",
            target_id=run_id,
            details={
                "packet_id": result.get("packet_id"),
                "trade_count": len(result.get("trade_timeline") or []),
                "review_required": bool(result.get("review_required")),
            },
        )
    return {
        "status": "ready",
        "understood": heard,
        "analysis_run_id": run_id,
        "result": result,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Whether the deterministic inputs this service depends on are present."""
    snapshots = sorted((SNAPSHOT_ROOT / "ECOS_USD_KRW").glob("*.json"))
    return {
        "ok": bool(snapshots),
        "fx_snapshots": [path.stem for path in snapshots],
        "database_backend": "postgresql" if DATABASE_URL else "sqlite-development",
        "document_encryption": "configured",
    }


if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")
