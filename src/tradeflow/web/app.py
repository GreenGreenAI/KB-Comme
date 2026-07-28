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

import os
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradeflow.agent.intake import intake
from tradeflow.runtime.accounts import SESSION_DAYS, Account, AccountStore
from tradeflow.agent.orchestrator import analyze
from tradeflow.agent.response import build_response
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

SESSION_COOKIE = "tradeflow_session"

#: Annotated rather than `= Cookie(default=None)`, so the real default is None.
#: With the old form the tests that call these endpoints as plain functions —
#: which is how every other endpoint here is tested — received the `Cookie`
#: marker object itself as the token.
SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]

app = FastAPI(title="TradeFlow", version="0.1.0")
accounts = AccountStore(ACCOUNT_DB)


class LoginRequest(BaseModel):
    email: str
    password: str


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


class AnalyzeRequest(BaseModel):
    cases: list[CaseInput] = Field(default_factory=list)
    utterance: str | None = None
    company_name: str = "미입력 기업"
    is_sme: bool | None = None
    opening_balance_usd: str | None = None
    baseline_profit: str | None = None
    profit_floor: str | None = None
    as_of: str | None = None
    #: Set only when the user has already answered "새 거래인가, 수정인가".
    #: Left unset, an ambiguous sentence comes back as a question instead of
    #: being resolved by a guess.
    placement: Literal["append", "merge"] | None = None


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

    reading = intake(
        supplied,
        company=account.profile() if account else None,
        company_name=request.company_name,
        is_sme=request.is_sme,
        opening_balances=balances,
        as_of=as_of,
    )

    if not reading.ready:
        return {
            "status": "needs_input",
            "understood": heard,
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

    analysis = analyze(
        reading.program,
        snapshot_root=SNAPSHOT_ROOT,
        baseline_profit=baseline_profit,
        profit_floor=profit_floor,
        utterance=request.utterance,
    )
    return {
        "status": "ready",
        "understood": heard,
        "result": build_response(analysis),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Whether the deterministic inputs this service depends on are present."""
    snapshots = sorted((SNAPSHOT_ROOT / "ECOS_USD_KRW").glob("*.json"))
    return {
        "ok": bool(snapshots),
        "fx_snapshots": [path.stem for path in snapshots],
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
