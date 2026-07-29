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

import hashlib
import logging
import os
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradeflow.agent.intake import intake
from tradeflow.domain.enums import TradeDirection
from tradeflow.knowledge.hedge_quotes import (
    HedgeQuoteSide,
    UserForwardQuote,
    UserQuoteHedgeAvailabilityService,
)
from tradeflow.runtime.accounts import SESSION_DAYS, Account, AccountStore
from tradeflow.runtime.coverage import statement as coverage_statement
from tradeflow.runtime.synthesis import Synthesizer, figures, pointer
from tradeflow.tools.intent import read_intent
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

#: §4.2[9]. Constructed whether or not a key is present — without one it simply
#: declines, and the screen writes its own sentence.
synthesizer = Synthesizer()
logger = logging.getLogger("tradeflow.synthesis")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class ForwardQuoteInput(BaseModel):
    """What a bank told this company, and nothing else.

    §5.3 will not produce a hedge ratio from public market data — a forward
    rate is what one bank offered to one company, and no snapshot can stand in
    for that. So these come from the user, who is the only one who has them,
    while everything about the quote's *scope* is derived from the trades
    already on file: which cases it covers, which currencies, which side, the
    settlement date. Asking for those again would invite an answer that does
    not match the analysis, and the availability service would then reject the
    quote for a mismatch the screen itself had caused.
    """

    provider: str = Field(min_length=1, max_length=64)
    contract_rate: str
    cost_rate: str
    valid_until: str
    #: The company confirming the bank actually offered this. §5.3 treats an
    #: indicative rate and a confirmed one differently, and only the person
    #: holding the quote can say which this is.
    confirmed: bool = False


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
    forward_quote: ForwardQuoteInput | None = None


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
            # What the subject they raised is, and is not, covered by. Said
            # here as well as on the answer because most sessions stop here —
            # a company asking about 제작 자금 should not have to supply an
            # amount and a date to find out we do not look at 수출입은행 자금.
            "coverage": _coverage(request.utterance),
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

    analysis = analyze(
        reading.program,
        snapshot_root=SNAPSHOT_ROOT,
        baseline_profit=baseline_profit,
        profit_floor=profit_floor,
        hedge_measures=_hedge_measures(request.forward_quote, reading.program, as_of),
        utterance=request.utterance,
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

    # Code-owned, and true whether or not the model answered. The sentence is
    # about the figures; this says what else the answer holds.
    result["pointer"] = pointer(result)
    result["coverage"] = _coverage(request.utterance)
    return {
        "status": "ready",
        "understood": heard,
        "result": result,
    }


def _coverage(utterance: str | None) -> str:
    """The limits of whatever the user just asked about.

    Only for the subject they raised. Reciting every limit on every turn
    teaches the reader to skip the line, and then it is not there on the turn
    that needed it — §4.2[2] already reads the subject, so this follows it.
    """
    if not utterance:
        return ""
    # Every subject the sentence named, not just the first. "베트남에 수출하는데
    # 정책자금이 있을까요" reads as (exposure, support) — exposure leads because
    # 수출 comes first — and taking only the lead said nothing about the half
    # of the question we cannot answer.
    said = [coverage_statement(section) for section in read_intent(utterance)]
    return " ".join(line for line in said if line)


def _hedge_measures(
    quote: ForwardQuoteInput | None,
    program: Any,
    as_of: date,
) -> tuple[Any, ...]:
    """The quote, scoped to the program it was given for.

    Everything the availability service checks for an exact match is computed
    here rather than asked for: the cases, the currencies, the side, the
    settlement date and the notional all follow from trades the user already
    entered. Collecting them a second time would let the two disagree, and the
    service would reject the quote over a contradiction the form had invented.

    Without a quote this returns nothing, and §5.3 stops with
    `FORWARD_QUOTE_REQUIRED` — which is the right answer, not a gap.
    """
    if quote is None:
        return ()

    cases = program.cases
    currency = cases[0].currency
    net = sum(
        case.amount if case.direction is TradeDirection.EXPORT else -case.amount
        for case in cases
        if case.currency == currency
    )
    if net == 0:
        return ()

    evaluated_at = datetime.combine(as_of, time(0, 0), tzinfo=UTC)
    try:
        confirmed = UserForwardQuote(
            quote_id=f"USERQUOTE-{as_of.isoformat().replace('-', '')}",
            provider_id=_provider_id(quote.provider),
            company_id=program.company.company_id,
            case_ids=tuple(case.case_id for case in cases),
            base_currency=currency,
            counter_currency="KRW",
            side=HedgeQuoteSide.SELL if net > 0 else HedgeQuoteSide.BUY,
            notional=abs(net),
            contract_rate=_money(quote.contract_rate, "contract_rate"),
            cost_rate=_money(quote.cost_rate, "cost_rate"),
            settlement_date=max(case.expected_payment_date for case in cases),
            quoted_at=evaluated_at,
            valid_until=_valid_until(quote.valid_until),
            confirmed=quote.confirmed,
        )
    except (ValueError, TypeError) as failure:
        raise HTTPException(
            status_code=422,
            detail={"field": "forward_quote", "reason": str(failure)},
        ) from None

    # The selection is the submission. §5.3 refuses to pick among quotes — with
    # several on file the company has to say which one it will use — and this
    # form takes one, which the user entered and sent. Leaving it unselected
    # would leave the measure `conditional` forever with nothing on screen able
    # to resolve it.
    service = UserQuoteHedgeAvailabilityService(
        quotes=(confirmed,),
        evaluated_at=evaluated_at,
        selected_quote_id=confirmed.quote_id,
    )
    return service.assemble(program=program, as_of=as_of).measures


def _provider_id(name: str) -> str:
    """A bank's name as an identifier the quote contract accepts.

    `UserForwardQuote` allows `[A-Za-z0-9._-]` only, and `"하나은행".isalnum()`
    is True — Python counts Hangul as alphanumeric, so a naive filter passed
    the name through unchanged and the contract rejected it.

    A digest keeps two banks apart and keeps the same bank stable across
    re-runs, which §6.2 needs. It does not keep the name: evidence will read
    `BANK_1f3c9a2b`, not `하나은행`. The name the user typed is on their screen
    and nowhere in the packet — worth raising with Role A, since the quote
    contract has no field for a display name.
    """
    cleaned = name.strip()
    if not cleaned:
        return "BANK"
    ascii_safe = "".join(
        ch for ch in cleaned if (ch.isascii() and ch.isalnum()) or ch in "._-"
    )
    if ascii_safe == cleaned:
        return f"BANK_{ascii_safe}"
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
    return f"BANK_{digest}"


def _valid_until(value: str) -> datetime:
    text = (value or "").strip()
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time(23, 59), tzinfo=UTC)
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"field": "valid_until", "reason": "ISO 날짜를 입력해 주세요"},
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
