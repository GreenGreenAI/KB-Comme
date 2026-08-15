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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tradeflow.agent.intake import intake
from tradeflow.domain.enums import TradeDirection
from tradeflow.knowledge.hedge_quotes import (
    HedgeQuoteSide,
    UserForwardQuote,
    UserQuoteHedgeAvailabilityService,
)
from tradeflow.runtime.accounts import SESSION_DAYS, Account, AccountStore
from tradeflow.domain.models import CompanyProfile
from tradeflow.runtime import asking, introduction, narration, observing, planner
from tradeflow.runtime.coverage import for_financing as coverage_for_financing
from tradeflow.runtime.coverage import statement as coverage_statement
from tradeflow.runtime.synthesis import (
    REFUSED_WORDING,
    Synthesis,
    Synthesizer,
    figures,
    pointer,
)
from tradeflow.tools.intent import read_intent
from tradeflow.agent.orchestrator import analyze, market_now
from tradeflow.agent.response import build_response
from tradeflow.tools.utterance_kind import (
    ABOUT,
    FOLLOW_UP,
    GREETING,
    TRADE,
    UNCLEAR,
    TRADE_SLOTS,
    asks_why,
    continues,
    read_kind,
)
from tradeflow.tools.utterance import (
    AMBIGUOUS,
    APPEND,
    DECLARABLE_STRUCTURE,
    financing_purpose,
    krw_amount,
    payment_structure,
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

#: 로그인은 닫혀 있습니다. 켜려면 `TRADEFLOW_SIGN_IN`을 세우세요.
#:
#: 화면에서 버튼을 내리는 것만으로는 닫힌 것이 아닙니다. `/api/auth/login`은
#: 그대로 열려 있었고, 주소를 아는 사람은 데모 계정으로 세션을 받을 수
#: 있었습니다 — 앞문은 잠겼는데 옆문이 열려 있는 상태입니다.
#:
#: 기본값이 닫힘인 것도 같은 이유입니다. 스위치를 켜는 것은 결정이지만 끄는
#: 것을 잊는 것은 사고이고, 인증은 사고 쪽이 훨씬 비쌉니다.
SIGN_IN_OPEN = bool(os.environ.get("TRADEFLOW_SIGN_IN"))

#: 계정 저장소는 쓸 때 열립니다.
#:
#: 모듈을 부르는 것만으로 `AccountStore`가 만들어지던 동안, 로그인을 쓰지 않는
#: 서버도 시작할 때마다 비밀번호 해시 저장소를 만들었습니다. 쓰지 않는 기능을
#: 위한 자격 증명 파일은 기능이 아니라 부채입니다.
_accounts: AccountStore | None = None


def accounts_store() -> AccountStore:
    global _accounts
    if _accounts is None:
        _accounts = AccountStore(ACCOUNT_DB)
    return _accounts


def _closed() -> HTTPException:
    """404, not 403.

    「닫혀 있습니다」는 여기에 문이 있다는 말이고, 그것은 이 배포에서는 사실이
    아닙니다. 없는 문을 두드린 것과 같은 답을 합니다."""
    return HTTPException(status_code=404, detail={"reason": "없는 경로입니다"})

#: §4.2[9]. Constructed whether or not a key is present — without one it simply
#: declines, and the screen writes its own sentence.
synthesizer = Synthesizer()
# Attached here rather than left to the operator. Every rejection §4.2[9] made
# was already being recorded and none of it arrived: uvicorn does not configure
# application loggers, so INFO was dropped at the root and the log held nothing
# while every synthesised sentence was being refused.
observing.listen()
logger = logging.getLogger("tradeflow.synthesis")


#: 모르는 필드는 받지 않습니다.
#:
#: Pydantic의 기본값은 모르는 필드를 조용히 버리는 것입니다. `opening_balances`를
#: `opening_balance_usd` 대신 보내면 서버는 200으로 답하고 그 값을 버렸습니다 —
#: 답 자체는 서버가 읽은 입력에 대해 정확하지만, 부른 쪽은 자기가 보낸 값이
#: 반영된 줄 압니다. 화면에도 아무 표시가 없습니다.
#:
#: 이 제품이 하는 말은 「입력한 값으로 계산했습니다」이고, 버려진 입력은 그 말을
#: 거짓으로 만듭니다. 그래서 422로 거부합니다 — 계산이 조용히 다른 입력 위에서
#: 도는 것보다 요청이 시끄럽게 실패하는 편이 낫습니다.
#:
#: 역할 A의 런타임 handoff 명세(#25)도 같은 것을 요구합니다 — 「Pydantic의 기본
#: extra-field 무시는 사용할 수 없다」.
STRICT = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    model_config = STRICT

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

    model_config = STRICT

    provider: str = Field(min_length=1, max_length=64)
    contract_rate: str
    cost_rate: str
    valid_until: str
    #: The company confirming the bank actually offered this. §5.3 treats an
    #: indicative rate and a confirmed one differently, and only the person
    #: holding the quote can say which this is.
    confirmed: bool = False


def _signed_in(token: str | None) -> Account | None:
    """Who the cookie says this is, or nobody.

    Closed, this never touches the store — so a leftover cookie cannot make an
    anonymous screen receive an answer judged on an account's company facts,
    and the store stays unopened.
    """
    if not SIGN_IN_OPEN:
        return None
    return accounts_store().read_session(token)


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    """Exchange a password for a session, or say no without saying why.

    One message for both failures. "그런 계정이 없습니다" would answer a
    question nobody asked — whether a given company banks here — to anyone
    willing to type addresses into the form.
    """
    if not SIGN_IN_OPEN:
        raise _closed()
    account = accounts_store().authenticate(body.email, body.password)
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
    if not SIGN_IN_OPEN:
        raise _closed()
    accounts_store().close_session(session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"account": None}


@app.get("/api/auth/me")
def me(session: SessionCookie = None) -> dict[str, Any]:
    """Who the server thinks you are.

    The screen asks rather than remembering, so being signed in is something
    the server says and not something the client decides about itself.
    """
    if not SIGN_IN_OPEN:
        raise _closed()
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

    model_config = STRICT

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
    model_config = STRICT

    cases: list[CaseInput] = Field(default_factory=list)
    utterance: str | None = None
    company_name: str = "미입력 기업"
    is_sme: bool | None = None
    #: §5.4's two most-asked company facts, for callers with no account. An
    #: account carries six; these are the two the eligibility rules name first,
    #: and without them a signed-out company asking about 지원제도 was told
    #: which facts were missing and given no way to state them.
    company_size: Literal["small", "mid_sized", "large"] | None = None
    credit_issue_free: bool | None = None
    opening_balance_usd: str | None = None
    baseline_profit: str | None = None
    profit_floor: str | None = None
    as_of: str | None = None
    #: Set only when the user has already answered "새 거래인가, 수정인가".
    #: Left unset, an ambiguous sentence comes back as a question instead of
    #: being resolved by a guess.
    #: The sentence this turn is still answering, when the turn itself has
    #: none. A request panel sends values and no words, and without this the
    #: answer forgot what the conversation was about between one turn and the
    #: next. Read for intent only — never for facts, which would let an
    #: already-answered sentence describe its trade twice.
    asked_about: str | None = None
    #: Ask the answer to carry a record of how it was produced — what each
    #: layer read and handed on, and how long each worker took. Off by default
    #: and deliberately so: the record contains the company's own facts, and an
    #: instrument that ships them to every caller is a leak with a switch.
    trace: bool = False
    placement: Literal["append", "merge"] | None = None
    forward_quote: ForwardQuoteInput | None = None
    #: What the company answered to the questions §5.4's rules raised, by field
    #: name. Validated against the fact catalog rather than typed here: the
    #: fields are the rules', and a second list of them in this module would be
    #: a copy that drifts the first time a rulepack changes.
    stated_facts: dict[str, str] | None = None
    #: The §5.5 trade structure earlier turns established — 상계, 제3자 지급,
    #: 상호계산. Held by the client and resent like the trade, because the
    #: server reads it out of the sentence and a follow-up has no sentence to
    #: read it from: 「상계로 처리합니다」 then 「왜?」 lost the netting and every
    #: branch that hung on it.
    declared_structure: dict[str, bool] | None = None
    #: 이번 턴에 답한 것이 무엇인지. 나머지 값은 매 턴 누적되어 통째로 오므로
    #: 서버 혼자서는 무엇이 새로 온 것인지 알 수 없고, 그래서 답할 때마다
    #: 무엇이 닫혔는지 말해 줄 수가 없었습니다. 화면은 알고 있습니다 — 방금
    #: 무엇을 눌렀는지가 곧 이 값입니다.
    #:
    #: 판정에는 쓰이지 않습니다. 이 값이 틀리거나 없으면 문장 한 줄이 빠질
    #: 뿐이고, 규칙은 언제나 누적된 사실 전부를 봅니다.
    just_answered: list[str] | None = None

    @field_validator("declared_structure")
    @classmethod
    def _known_structure_only(
        cls, given: dict[str, bool] | None
    ) -> dict[str, bool] | None:
        """Only fields §5.5's reader itself produces.

        This one is not checked against the fact catalog but against what
        `payment_structure` can say, which is narrower — the catalog holds
        fields no sentence declares, and a caller must not be able to assert
        one here just because it exists."""
        if not given:
            return given
        for field_name in given:
            if field_name not in DECLARABLE_STRUCTURE:
                raise ValueError(f"선언할 수 없는 거래 구조입니다: {field_name}")
        return given

    @field_validator("stated_facts")
    @classmethod
    def _known_facts_only(
        cls, given: dict[str, str] | None
    ) -> dict[str, str] | None:
        """Refuse a field the catalog does not know, or a value it would not
        accept, naming which — the same reason unknown fields are refused at
        all. A value that quietly vanishes here would be worse than one that
        vanishes at the edge, because the rule would then report the fact as
        missing and the screen would ask for it again."""
        if not given:
            return given
        for field_name, value in given.items():
            if not asking.accepts(field_name, value):
                raise ValueError(f"알 수 없거나 허용되지 않는 값입니다: {field_name}")
        return given


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

    # What the sentence is doing, before what it is missing. §4.2[1] counts
    # slots, and a greeting is missing all three exactly as a half-described
    # trade is — so counting alone answered "안녕" with a request for the
    # amount and the settlement date. Only turns with nothing else to say
    # reach the slot reader; a described trade goes straight past this.
    kind = read_kind(
        request.utterance,
        heard=heard,
        topics=read_intent(request.utterance or ""),
    )
    # 인사와 제품 질문은 화면에 거래가 있든 없든 인사와 제품 질문입니다.
    #
    # `supplied_trade`는 「거래를 버리면 안 된다」를 지키려고 있었는데, 인사에
    # 답하는 일과 거래를 버리는 일은 서로 다른 일입니다. 둘이 붙어 있어서
    # 대화 중간의 「안녕」이 계산 경로로 흘러 들어갔고, 아무것도 못 읽은 턴이
    # 되어 「그 문장에서는 거래 정보를 읽지 못해 계산이 달라지지 않았습니다」로
    # 돌아왔습니다. 인사에 대한 답으로는 이상합니다.
    #
    # 거래는 어차피 사라지지 않습니다 — 이 응답은 워커를 돌리지 않고 무엇도
    # 판정하지 않으며, 거래 목록은 화면이 들고 있습니다.
    #
    # TOPIC과 FOLLOW_UP은 그대로 둡니다. 거래를 앞에 두고 「환율은?」이나
    # 「왜?」를 물었다면 그건 그 거래에 대한 질문이고, 계산이 답입니다.
    holds_trade = supplied_trade(supplied)
    if kind in (GREETING, ABOUT):
        return _answer_without_a_trade(
            kind, request.utterance, as_of, _subjects(request), holds_trade=holds_trade
        )

    # 규칙이 읽어 낸 거래 정보가 하나도 없는 문장. 「고마워요」·「네 알겠습니다」·
    # 「좀 어렵네요」가 모두 여기로 떨어졌고, 인테이크 깔때기를 지나 「그 문장에서는
    # 거래 정보를 읽지 못해 계산이 달라지지 않았습니다」로 돌아왔습니다. 맞는
    # 말이지만, 방금 한 말에 대한 답은 아닙니다.
    #
    # 낱말 목록으로는 못 닫습니다 — 예의에는 유한한 어휘가 없습니다. 이 판단만
    # 모델에게 넘기는 것이 안전한 이유는 위치입니다. 규칙이 먼저 읽고 아무것도
    # 찾지 못한 뒤에만 옵니다. 진짜 거래 문장을 사교적이라 잘못 봐도 잃을 것이
    # 없고(어차피 읽힌 것이 없습니다), 사교적 문장을 아니라고 봐도 오늘과 같이
    # 동작합니다. 최악이 오늘이라서 여기서는 모델의 판단을 받습니다.
    unread = kind == UNCLEAR
    if unread and request.utterance:
        chat = synthesizer.converse(
            request.utterance,
            holds_trade=holds_trade,
            after=request.asked_about,
            seed=f"converse|{request.utterance}",
        )
        if chat.accepted:
            return {"status": "said", "understood": {}, "spoken": chat.sentence}
        if chat.reason:
            logger.info("대화 미채택: %s | %s", chat.reason, chat.sentence[:120])
        # 사교적이라고 읽긴 했는데 표현이 검사를 통과하지 못한 경우. 거절된
        # 것은 문장이지 읽기가 아니므로, 깔때기까지 되돌아가 「고마워요」에
        # 금액을 물으면 이 경로가 막으려던 바로 그 일이 됩니다.
        if chat.reason.startswith(REFUSED_WORDING):
            return {
                "status": "said",
                "understood": {},
                "spoken": introduction.acknowledgement(holds_trade=holds_trade),
            }

    # 주제도 후속질문도 아니고 화면에 거래도 없으면, 답할 거리가 없으니 묻습니다.
    # UNCLEAR는 여기서 빠집니다 — 방금 모델이 「거래 이야기였다」고 했거나 모델이
    # 없었다는 뜻이고, 둘 다 깔때기가 맞는 답입니다.
    if kind not in (TRADE, UNCLEAR) and not holds_trade:
        return _answer_without_a_trade(
            kind, request.utterance, as_of, _subjects(request), holds_trade=holds_trade
        )

    reading = intake(
        supplied,
        company=account.profile() if account else _stated_profile(request),
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
            "holds": _holds(request.utterance),
            "coverage": _coverage(request.utterance),
            # 읽지 못한 문장 뒤에 질문 세 개가 곧바로 오면 요구로 읽힙니다.
            # 못 알아들었다는 말이 먼저 있어야 그다음 질문이 요청이 됩니다 —
            # 이 자리에 오는 문장은 규칙도 모델도 무엇인지 정하지 못한 것이고,
            # 그렇게 말하는 것이 사실입니다.
            "unread": introduction.unread() if unread else "",
            # §4.2[1] in words. `questions` stays — the request panel pairs a
            # field with its own wording, and this one sentence covers all
            # three at once. What is asked for is still decided by the slot
            # reader; only the phrasing comes from the model, and an empty
            # `spoken` leaves the screen listing `questions` as before.
            "spoken": synthesizer.ask_for(
                list(reading.missing),
                understood=heard,
                question=request.utterance,
                subjects=list(read_intent(request.utterance or "")),
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
                *(
                    [
                        {
                            "field": "amount",
                            "reason": (
                                # Not "환노출은 …" — this limit holds
                                # whatever was asked about, and naming the
                                # exposure calculation to someone who asked
                                # about 제작 자금 answered a question they
                                # had not put.
                                f"{stated_krw:,.0f}원으로 들었습니다. 지금은 "
                                "미국 달러 거래를 기준으로 분석하므로 달러 "
                                "금액이 따로 필요합니다."
                            ),
                        }
                    ]
                    if (stated_krw := krw_amount(request.utterance or ""))
                    and "amount" in reading.missing
                    else []
                ),
                *(
                    {"field": issue.field, "reason": issue.reason}
                    for issue in reading.issues
                ),
            ],
        }

    analysis = analyze(
        reading.program,
        snapshot_root=SNAPSHOT_ROOT,
        baseline_profit=baseline_profit,
        profit_floor=profit_floor,
        hedge_measures=_hedge_measures(request.forward_quote, reading.program, as_of),
        utterance=request.utterance,
        intent=_subjects(request),
        answered_facts=request.stated_facts,
        declared_structure=request.declared_structure,
        # The day the analysis is for, not the instant it ran. §6.2 asks that
        # the same analysis produce the same `packet_id`, and every evidence
        # descriptor is stamped with this. Left unset it became
        # `datetime.now()`, so two identical requests a second apart produced
        # two different packets — the identity said the inputs had changed when
        # only the clock had.
        #
        # The orchestrator had this right and said so (ADR-0007). The web layer
        # was the one caller that never passed it, so the guarantee held in
        # every test and in no request.
        as_of=datetime.combine(as_of, time(0, 0), tzinfo=UTC),
    )
    result = build_response(analysis)

    # §4.2[9]: the last step, and the only one a language model touches. It is
    # given the figures the tools produced and nothing else, and what it writes
    # is checked against them before it is used. A refusal — no key, no
    # network, or a sentence that invented a number — leaves `summary` empty
    # and the screen assembles its own sentence, so prose is the only thing
    # that can be lost here.
    written = synthesizer.write(
        figures(result),
        question=request.utterance,
        subjects=list(read_intent(_subject_text(request))),
        # The packet identifies the analysis (§6.2) and the sentence identifies
        # the question. Together they decide the decoding, so the same answer
        # to the same question reads the same and the next one does not
        # inherit its wording.
        seed=f"{result.get('packet_id')}|{_subject_text(request)}",
        direction=(result.get("market_scenario") or {}).get(
            "adverse_cashflow_direction"
        ),
    )
    if written.accepted:
        result["summary"] = written.sentence
    elif written.reason:
        logger.info("합성 미채택: %s | %s", written.reason, written.sentence[:120])

    # What the conversation is about, for everything below. This turn's own
    # words when it has any; otherwise the question still on the table.
    subject = _subject_text(request)

    # Code-owned, and true whether or not the model answered. The sentence is
    # about the figures; this says what else the answer holds.
    subjects = tuple(result["execution_plan"]["topics"])
    # Said whether or not a trade is on screen. That this product judges
    # eligibility and does not describe schemes is true either way, and it
    # lived only on the path taken when there was no trade — so the moment a
    # company had described one, every question about what something is came
    # back as an analysis of that trade with no word about the question.
    meaning = _asks_meaning(request.utterance)
    result["cannot"] = (
        CANNOT.get(next(iter(subjects), ""), "") if meaning else ""
    )
    # 로그인 안내는 붙이지 않습니다. 기업규모와 신용 상태를 물은 문장 뒤에
    # 「로그인하시면 계정 사실로 판정합니다」를 덧붙이면, 방금 요청한 두 사실을
    # 다시 요청하는 두 번째 요청이 되어 읽는 사람이 무엇을 해야 하는지가
    # 하나에서 둘로 늘어납니다. 계정이 그 사실을 들고 있다는 것은 로그인 화면이
    # 말할 일이지 판정 결과가 말할 일이 아닙니다.
    result["pointer"] = pointer(result, intent=subjects)
    # The judgements as sentences. Written here rather than by §4.2[9], which
    # may not utter a verdict, and rendered as prose rather than as folds —
    # a record is something you audit, not something you read.
    result["said"] = {
        "support": narration.support(result),
        "compliance": narration.compliance(result),
        "actions": narration.actions(result),
        "sources": narration.sources(result),
        "detail": narration.detail(result),
        # 같은 판정을, 근거를 달고. `support`·`compliance`·`actions`가 쓴
        # 문장들을 문단으로 이어 붙이고 그 근거를 접힘 하나에 모아 두면,
        # 읽는 사람은 주장 하나를 머리에 넣고 접힘을 열어 해당하는 줄을 찾아
        # 돌아와야 한다. 근거가 있는데 쓸 수 없는 상태이고, 그건 없는 것보다
        # 나쁘다 — 화면은 일을 보여주는 척하면서 그 일을 읽을 수 없게 만든다.
        "grounded": narration.grounded(result),
    }
    # 답변에서 가장 큰 숫자가 유일하게 근거 없이 서 있었다. 규칙 판정은
    # 적어도 펼쳐 볼 수 있었는데, 은행에 그대로 옮겨 적을 가능성이 가장 높은
    # 손실 금액은 어디서 왔는지 말하지 못했다.
    result["basis"] = narration.basis(result)
    # 들은 것을 먼저 돌려줍니다. 이 줄은 되묻기 턴에만 있었고, 답을 낸 턴에는
    # 없었습니다 — 문장이 온전히 이해된 회사만 이해됐다는 표시를 못 받고,
    # 답변이 아직 필요한 것으로 시작했습니다.
    result["read_back"] = narration.read_back(heard)
    # 답할 때마다 무엇이 닫혔는지. 규칙은 매 턴 조건을 지나보내고 있었는데
    # 화면은 그중 아무것도 말하지 않아서, 답하는 일이 계속 늘어나는 양식을
    # 채우는 것처럼 느껴졌습니다 — 실제로는 한 번의 답이 이름 있는 제도의
    # 이름 있는 조건을 닫고 있었습니다.
    result["closed"] = narration.closed(result, request.just_answered)
    # 자금 공백이 언제 열리고 며칠인지. 금액만 있는 공백은 걱정이고, 날짜가
    # 붙은 공백은 할 일이다 — 8월 25일에 6만 달러가 있느냐 없느냐는 숫자만
    # 보아서는 알 수 없다. 응답에 이미 있던 타임라인에서 두 번 찾으면 나온다.
    result["funding_window"] = narration.funding_window(result)
    # 「왜?」 is the one follow-up this product answers well, because the answer
    # was already in the packet: every rule records the conditions it checked.
    # They sat in a fold, which is right until somebody asks — and then the
    # thing they asked for is one click away and the answer is not on screen.
    #
    # Only when asked. Every judgement carrying its reasons in the first
    # paragraph is the record this product spent a week turning into sentences.
    result["because"] = (
        narration.because(result) if asks_why(request.utterance) else []
    )
    # What the server ended up holding about the trade structure — this turn's
    # sentence merged over what the client sent. Echoed so the next turn can
    # send it back: the browser is where this conversation is kept, and it can
    # only keep what it is told. The reading stays the server's; the client
    # carries it and nothing more.
    result["declared_structure"] = dict(analysis.declared_structure)
    # Whether this turn was pointing at the last one rather than describing
    # anything. The screen says 「그 문장에서는 거래 정보를 읽지 못했습니다」
    # when a sentence changed nothing, which is right for a sentence that tried
    # to say something and wrong for 「왜?」 — that one was not trying.
    result["follows"] = bool(
        request.utterance
        and continues(request.utterance)
        and not read_intent(request.utterance)
    )
    # §4.2[9] again, on the judgements this time — but only to retell them.
    # The instruction asks it to invent nothing; `check_retold` is what makes
    # that a contract rather than a request. A refusal leaves the assembled
    # sentences, which are already true and already complete.
    #
    # 신고의무는 넘기지 않는다. §5.5는 「아직 모름」이 「없음」으로 읽히는 것을
    # 금지하고, 그 금지는 「신고가 불필요하다는 판정은 아닙니다」라는 한 문장에
    # 실려 있다. 재작성은 그 문장을 지웠다 — 짧아졌고, 잘 읽히고, 회사는
    # 신고 의무가 없다고 믿게 된다. 모델은 찾은 것을 다시 말할 수 있고,
    # 보류한 것을 다시 말할 수는 없다.
    # One answer, not four strands stitched together. Everything the workers
    # produced goes in at once — the figures sentence, the eligibility
    # judgements, the filing branches, the next action — and comes back as one
    # piece of prose. What keeps that safe is not the instruction but
    # `check_retold`: nothing new, nothing dropped, and the sentences §5.5
    # rests on carried word for word.
    told = [
        *([result["summary"]] if result.get("summary") else []),
        *result["said"]["support"],
        *result["said"]["compliance"],
        *result["said"]["actions"],
    ]
    # A rewrite exists to make several judgements read as one answer. Given a
    # single line it has nothing to combine and becomes a machine that says the
    # same thing twice — the screen then showed both, three lines apart, in the
    # same words. Fewer than two judgements is not an answer that needs one.
    retold = Synthesis("", False, "합칠 판정이 없습니다")
    if len(told) > 1 and any(
        result["said"][section] for section in ("support", "compliance", "actions")
    ):
        retold = synthesizer.retell(
            told,
            # Every subject the rules judged. A rewrite may shorten a name; it
            # may not leave a judgement out.
            subjects=tuple(
                row["title"]
                for row in result["said"]["detail"]
                if row["title"] != "필요서류"
            ),
            # §5.5's refusal to read 「아직 모름」 as 「없음」 lives in one
            # sentence. A rewrite dropped it the first time it was near it.
            required=tuple(
                line
                for line in result["said"]["compliance"]
                if "판정은 아닙니다" in line
            ),
            seed=f"retell|{result.get('packet_id')}",
        )
    if retold.accepted:
        result["said"]["retold"] = retold.sentence
    elif retold.reason:
        logger.info("재작성 미채택: %s | %s", retold.reason, retold.sentence[:120])
    # The pointer exists because the synthesised sentence may not carry a
    # verdict. When the narration carries one, the pointer is the same claim
    # twice — and the reader met it twice, three lines apart.
    if any(result["said"].get(section) for section in subjects):
        result["pointer"] = ""
    if request.trace:
        result["trace"] = _trace(request, reading, analysis, subject)
    result["holds"] = _holds(subject)
    result["coverage"] = _coverage(subject)
    # Which of the two the reader meets first. §4.2[9]'s sentence may only
    # quote `figures()`, and every figure in it is an exposure, a rate or a
    # hedge ratio — that is the whole safety division and it stays. But a
    # company that asked about 제작 자금 then opened the answer on its
    # exchange-rate exposure, because the one sentence a model may write is
    # always about the one subject it may quote. The judgement it asked for
    # was two lines further down, in the code-owned pointer.
    #
    # Ordering only. Nothing is added, removed or re-worded.
    result["lead"] = "pointer" if _leads(subjects) else "summary"
    # What to ask for next, chosen by what was asked about. Every blocked
    # worker still reports its reason in its own fold — nothing is hidden —
    # but only one of them gets the top of the screen and an input panel.
    # A company that asked whether its netting is reportable was being asked
    # for its operating profit, which is §5.3's input and nobody's answer.
    # A panel is a demand. Opening one under a question we have just said we
    # cannot answer asks the reader to supply facts for something they did not
    # ask about. The sentence still names what would unlock the judgement, so
    # nothing is withheld — it is offered instead of demanded.
    result["asking_for"] = None if result["cannot"] else _asking_for(subjects, result)
    # The facts §5.4 is waiting for, when the caller is the one who can state
    # them. A signed-in company already stated them once and is never asked.
    result["required_inputs"]["profile"] = (
        [
            attribute
            for attribute in STATED_COMPANY_FACTS
            if getattr(request, attribute) is None
        ]
        if account is None and "support" in ((result.get("workers") or {}).get("skipped") or {})
        else []
    )
    # And the facts a rule that *did* run is still short of. The two are
    # different questions: the profile above opens the worker, these close the
    # judgements it produced. Only the second kind was being reported by the
    # rules and never asked, so a company could answer everything on screen and
    # still watch two of three products come back 「아직 판정하지 못했습니다」
    # listing conditions nobody was going to be asked about.
    result["required_inputs"]["facts"] = asking.questions(
        result,
        already=request.stated_facts,
        # What each trade already carries. Without it a question the company
        # has answered comes back every turn, because a slot that was filled
        # does not always produce the fact the rule wanted.
        supplied=frozenset(
            (case.case_id, slot)
            for case in reading.program.cases
            for slot in asking.slots_of()
            if case.attributes.get(slot)
        ),
    )
    return {
        "status": "ready",
        "understood": heard,
        "result": result,
    }


#: Subjects the synthesised sentence can be about. A question about anything
#: else is answered by the pointer, so the pointer goes first.
_SENTENCE_SUBJECTS = frozenset({"exposure", "market_scenario", "hedge"})


def _trace(
    request: AnalyzeRequest,
    reading: Any,
    analysis: Any,
    subject: str,
) -> dict[str, Any]:
    """What each layer read and what it handed on.

    The response already showed the *result* of every layer — the plan, the
    workers, the packet. What it never showed was the flow: which slots intake
    read out of the sentence, which facts the orchestrator asserted, which of
    them reached the rules. Finding out why `financing.purpose` was never
    filled meant reading the code, because no answer said what had been handed
    across.

    Nothing here is used to decide anything. It is a mirror held up to a
    request that has already been answered.
    """
    program = getattr(reading, "program", None)
    return {
        "utterance": {
            "kind": read_kind(
                request.utterance,
                heard=read_utterance(request.utterance or "", as_of=_analysis_date(request.as_of)),
                topics=read_intent(request.utterance or ""),
            ),
            "intent": list(read_intent(subject)),
            "slots": read_utterance(
                request.utterance or "", as_of=_analysis_date(request.as_of)
            ),
            "financing_purpose": financing_purpose(request.utterance),
            "payment_structure": payment_structure(request.utterance),
        },
        "intake": {
            "ready": getattr(reading, "ready", None),
            "missing": list(getattr(reading, "missing", ())),
            "cases": len(getattr(program, "cases", ()) or ()),
            "company_facts": sorted(
                (program.company.facts() if program is not None else {}) or {}
            ),
        },
        "plan": analysis.plan.as_dict(),
        "workers": {
            "completed": list(analysis.report.completed),
            "failed": analysis.report.failed,
            "skipped": sorted(analysis.report.skipped),
            "took_seconds": analysis.report.took,
        },
        "knowledge": {
            "declared_structure": dict(analysis.declared_structure),
            "decisions": len(
                (analysis.decision_packet.decisions if analysis.decision_packet else ())
            ),
            "evidence": sorted(
                {
                    item.evidence_id
                    for item in (
                        analysis.decision_packet.evidence
                        if analysis.decision_packet
                        else ()
                    )
                }
            ),
        },
    }


def _subjects(request: AnalyzeRequest) -> tuple[str, ...]:
    """What this turn is about — keywords first, the model appending.

    The keyword reading keeps its lead, so every routing case pinned in
    `tests/acceptance/routing.json` still holds whatever the model says. What
    the model can do is notice a subject the word lists have no entry for:
    「지금 환전해 두는 게 나을까요」 names no hedge word and is a hedge
    question, and 「거래처가 망하면 대금을 못 받을 텐데」 names no support word
    and is asking which insurance covers it.
    """
    said = _subject_text(request)
    return planner.widen(said, read_intent(said), synthesizer=synthesizer, seed=said)


def _subject_text(request: AnalyzeRequest) -> str:
    """The sentence whose subject this turn is answering.

    This turn's own words when it has any; otherwise the question still on the
    table. Only the subject is taken from the older sentence — the slot reader
    never sees it, so a trade described once is not described again.

    A follow-up counts as having none. 「왜?」 and 「그럼?」 are made of pointing
    words and nothing else: read alone they name no subject, and the answer came
    back in the default order as if the conversation had just started. What they
    are about is what the last sentence was about.

    Ordering only, here as everywhere. The older sentence reaches `read_intent`
    and stops there.
    """
    said = request.utterance or ""
    if not said.strip():
        return request.asked_about or ""
    if request.asked_about and continues(said) and not read_intent(said):
        return request.asked_about
    return said


def _leads(subjects: tuple[str, ...]) -> bool:
    """True when the first thing asked about is not what the summary can say.

    Silence — a trade description with no question — keeps the default order.
    """
    lead = next(iter(subjects), None)
    return lead is not None and lead not in _SENTENCE_SUBJECTS


#: The company facts a request body may state, and where §5.4 reads them.
STATED_COMPANY_FACTS = {
    "company_size": "company.size",
    "credit_issue_free": "company.credit_issue_free",
}


def _stated_profile(request: AnalyzeRequest) -> CompanyProfile | None:
    """A profile from what the caller typed, for callers with no account.

    An account is the better place for these — it holds six facts, states them
    once, and does not ask again next session. This is the same facts by hand,
    so a company that has not signed up still gets a judgement rather than a
    list of what it would need.

    Nothing stated produces no profile at all: §5.4 must go on reporting the
    facts as missing rather than being handed an invented `False`. `is_sme`
    follows from the size when the size is given — they are the same claim, and
    letting them disagree would be a contradiction the rules cannot see.
    """
    stated = {
        fact: getattr(request, attribute)
        for attribute, fact in STATED_COMPANY_FACTS.items()
        if getattr(request, attribute) is not None
    }
    is_sme = request.is_sme
    if request.company_size is not None:
        is_sme = request.company_size in ("small", "mid_sized")
    if not stated and is_sme is None:
        return None
    return CompanyProfile(
        company_id="COMPANY-001",
        name=request.company_name,
        is_sme=is_sme,
        attributes=stated,
    )


def supplied_trade(cases: list[dict[str, Any]]) -> bool:
    """Whether the form already holds anything about a trade.

    A greeting typed into a session that has a trade on screen is still a
    greeting, but it must not discard what is there — so the trade-less path
    is only taken when there is genuinely no trade anywhere.

    「거래」 is judged the same way `read_kind` judges it: an amount or a date.
    A direction on its own is not one, and 「환변동보험에 대해 설명해줘」 puts a
    direction into the case list on its way past — which made the sentence look
    like a trade already on screen and sent it back to the funnel it had just
    been kept out of.
    """
    return any(
        any(case.get(slot) for slot in TRADE_SLOTS) for case in cases
    )


def _answer_without_a_trade(
    kind: str,
    utterance: str | None,
    as_of: date,
    subjects: tuple[str, ...] = (),
    *,
    holds_trade: bool = False,
) -> dict[str, Any]:
    """The three turns that are not a trade description.

    None of them needs a trade, and all three used to get the same three
    questions. What is said here is either fixed prose or read straight off a
    snapshot — no worker runs, no packet is produced, and nothing is judged.
    """
    if kind == GREETING:
        return {
            "status": "said",
            "understood": {},
            "spoken": introduction.opening(holds_trade=holds_trade),
        }
    if kind == ABOUT:
        return {"status": "said", "understood": {}, "spoken": introduction.paragraph()}

    # TOPIC. Some subjects have an answer that stands on its own; the rest
    # still need the trade, and asking for it is right — after saying what
    # did not need it, and after saying what we do not do at all.
    lead = next(iter(subjects), "")
    said, figures = _standing_answer(utterance, as_of)
    return {
        "status": "said" if said else "needs_input",
        "understood": {},
        "spoken": said,
        "figures": figures,
        "questions": [] if said else [],
        "coverage": _coverage(utterance),
        "holds": _holds(utterance),
        # Said whether or not the standing part answered: the subject they
        # raised may still need the trade, and this is the sentence that says
        # so instead of leaving them waiting.
        "asks_for_trade": ASK_FOR_TRADE.get(lead, DEFAULT_ASK),
        # Named before the ask. A company that asked what a scheme is should
        # learn that we do not answer that before being told what we want.
        "cannot": CANNOT.get(lead, "") if _asks_meaning(utterance) else "",
    }


#: What this product does not do about a subject, said only when someone asks
#: about that subject without a trade.
#:
#: 「환변동보험에 대해 설명해줘」 has no trade in it and no answer here. The
#: rules judge whether a company qualifies; nothing in the product describes
#: what a scheme is for, because a description with no source is the one thing
#: §1.1 refuses and the extracts hold eligibility conditions only.
#:
#: Saying so is the answer. Asking for an amount and a settlement date is not —
#: that is the funnel answering a question it did not read.
#: A sentence asking what something *is*, as distinct from whether it applies.
#:
#: 「환변동보험이 뭐야」 and 「받을 수 있는 지원제도가 있나요」 read as the same
#: subject and want different things. The first has no answer here and the
#: second does, so the honest line and the request panel both hang on telling
#: them apart. Kept tight on purpose: 「지원제도 알려줘」 is asking which ones,
#: not what they are, and belongs on the judging side.
_ASKS_MEANING = (
    "뭐야",
    "뭔가요",
    "뭔지",
    "무엇인가",
    "무엇인지",
    "이란",
    "란 게",
    "설명해",
    "설명 좀",
    "어떤 제도",
    "무슨 제도",
    "차이가",
    "차이점",
)


def _asks_meaning(utterance: str | None) -> bool:
    return bool(utterance) and any(word in utterance for word in _ASKS_MEANING)


#: 「다만」으로 시작하지 않습니다. 이 문장은 이제 답의 맨 앞에 오고,
#: 앞선 말이 없는 자리에서 역접 부사는 읽는 사람에게 놓친 문장을 찾게 합니다.
CANNOT = {
    "support": (
        "제도가 무엇인지 설명하는 것은 아직 다루지 않습니다. "
        "출처에 근거가 없는 설명은 드리지 않습니다."
    ),
    "compliance": (
        "제도나 용어를 설명하는 것은 아직 다루지 않습니다. "
        "외국환거래법 조문에 근거해 이 거래가 신고 대상인지를 판정합니다."
    ),
}

#: What each subject still needs from the trade, once the standing part of the
#: answer has been given. Written per subject because "금액과 날짜를 알려주세요"
#: after a rate quote reads as the product having ignored its own answer.
ASK_FOR_TRADE = {
    "market_scenario": (
        "이 환율이 특정 거래에 얼마인지 보시려면, 수출인지 수입인지와 금액, "
        "대금을 주고받기로 한 날짜를 알려주세요."
    ),
    "hedge": (
        "헤지비율은 거래가 있어야 계산합니다. 수출인지 수입인지와 금액, "
        "대금을 주고받기로 한 날짜를 알려주세요."
    ),
    "exposure": (
        "노출을 계산하려면 수출인지 수입인지와 금액, 대금을 주고받기로 한 "
        "날짜가 필요합니다."
    ),
    "support": (
        "자격을 판정하려면 수출인지 수입인지와 금액, 대금을 주고받기로 한 "
        "날짜를 알려주세요."
    ),
    "compliance": (
        "신고 의무는 거래 구조에서 발생하므로, 거래를 알려주시면 판정합니다."
    ),
}

DEFAULT_ASK = (
    "거래를 알려주시면 노출과 지원제도·신고의무를 함께 봐 드립니다."
)


def _standing_answer(utterance: str | None, as_of: date) -> tuple[str, list[str]]:
    """The part of the subject that holds without a trade.

    Today that is the published rate and the window behind it. It is read from
    the same snapshot the band uses, under the same freshness policy, so a
    number said here cannot disagree with the same number said in an answer.
    A stale or absent snapshot says nothing rather than quoting an old rate.
    """
    topics = read_intent(utterance or "")
    if "market_scenario" not in topics:
        return "", []
    try:
        now = market_now(SNAPSHOT_ROOT, as_of=datetime.combine(as_of, time(0, 0), tzinfo=UTC))
    except Exception as failure:  # noqa: BLE001 — stale, missing, unreadable
        logger.info("환율 단독 응답 미채택: %s", type(failure).__name__)
        return "", []
    figures = [
        f"현재 환율: {now.spot_rate} (KRW per USD, 한국은행 매매기준율 "
        f"{now.observed_on.isoformat()} 기준)",
        f"연환산 변동성: {now.annualized_volatility:.1%} "
        f"(최근 {now.window}영업일, {now.first_observed.isoformat()}~"
        f"{now.last_observed.isoformat()})",
    ]
    return "\n\n".join(figures), figures


#: Which blocked worker each subject would want unblocked. A subject not
#: listed has nothing to collect beyond the trade itself.
_UNBLOCKS = {"hedge": "hedge", "exposure": "hedge", "support": "support"}


def _asking_for(topics: tuple[str, ...], result: dict[str, Any]) -> str | None:
    """The one worker whose missing input is worth the top of the screen.

    §4.2[2] already decides why each worker was skipped and every reason is
    rendered in its own fold. This decides which of them is also the thing
    the reader is asked for right now — an input panel is a demand, and a
    demand for a value the question did not need reads as the product not
    having listened.

    A sentence that asked about nothing in particular keeps the old behaviour:
    a plain trade description is the funnel's own case, and §2's reader does
    not know their exposure well enough to ask about it by name.
    """
    skipped = (result.get("workers") or {}).get("skipped") or {}
    if not topics:
        return "hedge" if "hedge" in skipped else None
    for topic in topics:
        worker = _UNBLOCKS.get(topic)
        if worker and worker in skipped:
            return worker
    return None


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


def _holds(utterance: str | None) -> str:
    """What this product does hold for the money the company says it needs.

    Separate from `_coverage` because it is not a limit and must not be set in
    the type limits are set in. Folded into that grey block it became the
    faintest line on a screen whose entire subject it was.
    """
    return coverage_for_financing(financing_purpose(utterance))


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
