import { useEffect, useRef, useState } from "react";

/** Kept in step with the .menu transition in styles.css. */
const MENU_EXIT_MS = 150;

/** Signed out offers a way to get an account; signed in shows who you are.
 *  The menu is built from this product's own concepts — what is saved here is
 *  what the intake agent no longer has to ask for.
 *
 *  Whether anyone is signed in is App's to know, not this bar's: the sign-in
 *  page is a view of the app, and a header cannot decide which view the app is
 *  showing. The bar only reports the state and offers the way out of it.
 *
 *  Signed out, the bar has no 로그인 button. The whole screen already is the
 *  sign-in form, and a button that scrolls you to what you are looking at is
 *  noise — what is missing at that moment is a way in for someone with no
 *  account at all. */
/** The facts §5.4 reads, in the words a person uses for them.
 *
 *  Only what the account actually states is listed. A fact it is silent about
 *  is left out rather than shown as "아니요" — that silence is what makes the
 *  rules ask, and writing an answer in for them here would be the screen
 *  deciding something the analysis refused to decide. */
const FACT_LABEL = {
  "company.is_sme": (v) => (v ? "중소기업" : "중소기업 아님"),
  "company.size": (v) => ({ small: "소기업", medium: "중기업", large: "대기업" }[v] ?? v),
  "company.industry_code": (v) => `업종 ${v}`,
  "company.credit_issue_free": (v) => (v ? "신용 이슈 없음" : "신용 이슈 있음"),
  "company.ksure_exporter_grade": (v) => `K-SURE 등급 ${v}`,
  "company.is_domestic": (v) => (v ? "국내 소재" : "국외 소재"),
};

function described(facts) {
  return Object.entries(facts ?? {})
    .filter(([name]) => name in FACT_LABEL)
    .map(([name, value]) => FACT_LABEL[name](value));
}

export default function Nav({
  onHome,
  account,
  //: 대화를 내려놓고 다시 시작합니다. 브랜드 클릭과 다른 의도라 다른 버튼을
  //: 씁니다 — 하나는 처음 화면으로 가고 대화는 그대로 두는 것입니다.
  onStartOver,
  onSignIn,
  signingIn,
  onSignOut,
  //: 로그인이 닫혀 있으면 이 바에는 계정 자리가 없습니다. 들어갈 문이
  //: 없는데 문고리만 그려 두면, 눌리지 않는 것이 준비 중인지 고장인지
  //: 화면이 말해 주지 못합니다.
  signInOpen = true,
}) {
  const signedIn = Boolean(account);
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  // The menu has to outlive `open` for as long as it takes to leave. Rendering
  // it only while open removed it from the DOM on the same frame the close was
  // requested, so there was nothing left to animate out.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    // Matches the CSS duration. Shorter and the menu is cut off mid-exit;
    // longer and clicks pass through something the eye no longer sees.
    const timer = setTimeout(() => setMounted(false), MENU_EXIT_MS);
    return () => clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const away = (event) => {
      if (!box.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event) => event.key === "Escape" && setOpen(false);
    document.addEventListener("click", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("click", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <header className="nav">
      <button className="brand" type="button" onClick={onHome}>
        <i>T</i> TradeFlow
      </button>
      {/* The three areas beyond 분석 have no page behind them yet. They are
          shown so the shape of the product is legible, and they respond to the
          pointer so they do not read as dead text — but the cursor stays an
          arrow and aria-disabled says what a hover cannot. A link that looks
          like a link and goes nowhere is worse than one that says "준비 중". */}
      {/* The areas belong to the signed-in product. Showing them over a
          sign-in form would list rooms nobody can enter yet. Left out rather
          than hidden: the `hidden` attribute loses to this bar's own
          `display: flex`, so it would have shown anyway. */}
      {/* 로그인이 닫혀 있는 동안에는 로그인하지 않은 사람이 곧 사용자이므로,
          영역은 그대로 보입니다. 이 목록을 감췄던 이유는 로그인 폼 위에
          들어갈 수 없는 방을 늘어놓지 않으려던 것이고, 그 폼이 없으면
          그 이유도 없습니다. */}
      {(signedIn || !signInOpen) && (
      <nav aria-label="주요 영역">
        <span className="nav-link on" aria-current="page">분석</span>
        {["지원제도", "신고의무", "근거"].map((area) => (
          <span
            key={area}
            className="nav-link soon"
            aria-disabled="true"
            title="준비 중"
          >
            {area}
          </span>
        ))}
      </nav>
      )}

      <div className="account" ref={box}>
        {onStartOver && (
          <button className="nav-cta quiet" type="button" onClick={onStartOver}>
            새 대화
          </button>
        )}
        {!signInOpen ? null : !signedIn ? (
          signingIn ? (
            /* On the sign-in screen itself, a 로그인 button would point at
               what is already on the screen. What is missing there is a way in
               for someone with no account — and there is no sign-up behind it,
               so it says so instead of pretending. */
            <div className="nav-invite">
              <span>계정이 없으신가요?</span>
              <button className="nav-cta" type="button" disabled title="준비 중">
                가입 신청
              </button>
            </div>
          ) : (
            <button className="nav-cta" type="button" onClick={onSignIn}>
              로그인
            </button>
          )
        ) : (
          <>
            <button
              className="avatar"
              type="button"
              aria-expanded={open}
              aria-haspopup="true"
              aria-label="계정 메뉴"
              onClick={() => setOpen((v) => !v)}
            >
              {account.company_name.slice(0, 1)}
            </button>
            {/* Entering and leaving are separate animations rather than one
                transition between classes. A transition needs the element to
                paint in its start state before the class flips, which means
                waiting for a frame; mounting straight into an animation does
                not. */}
            {mounted && (
              <div className={`menu ${open ? "" : "out"}`}>
                <div className="menu-id">
                  <span className="avatar" aria-hidden="true">
                    {account.company_name.slice(0, 1)}
                  </span>
                  <div>
                    <b>{account.company_name}</b>
                    <span>{account.email}</span>
                  </div>
                </div>
                {/* The facts themselves, not a count of them. These are the
                    same values the server puts into DecisionPacket.inputs, so
                    what is listed here is what the judgement was made on —
                    the menu used to state a company the analysis had never
                    heard of. */}
                <div className="menu-facts">
                  {described(account.facts).map((fact) => (
                    <span key={fact}>{fact}</span>
                  ))}
                  {described(account.facts).length === 0 && (
                    <span className="none">저장된 기업 사실이 없습니다</span>
                  )}
                </div>
                <p className="note">
                  이 사실들은 분석 요청에 그대로 실립니다. 규칙이 묻지 않은 것은
                  계정에도 없습니다.
                </p>
                <hr />
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    setOpen(false);
                    onSignOut();
                  }}
                >
                  로그아웃
                </a>
              </div>
            )}
          </>
        )}
      </div>
    </header>
  );
}
