import { useState } from "react";
import { signIn } from "./api.js";

/** The way in.
 *
 *  Two halves that say different things. The left says why an account is worth
 *  having — and it says it in this product's own terms: what is kept is the
 *  calculation and the rate it used, not "your data". The right is the form,
 *  and it is deliberately dull. A sign-in box is somewhere the hand goes, not
 *  somewhere the eye lingers.
 *
 *  The form authenticates. What it does not do is decide the answer: the
 *  password goes to the server, the server compares it against a stored scrypt
 *  digest and sets the session cookie, and this component learns whether it
 *  worked from the reply. Nothing about being signed in is decided here, so
 *  nothing about it can be arranged from here either.
 *
 *  There is no sign-up. Accounts are seeded (scripts/seed_accounts.py), and the
 *  two alternatives below are the ones a Korean SME really uses — neither is
 *  connected to anything, so both say so rather than pretending.
 */
export default function Login({ onSignIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onSignIn(await signIn(email, password));
    } catch (failure) {
      // One message for both failures, because the server sends one. Saying
      // "그런 계정이 없습니다" would answer a question nobody asked.
      setError(failure.message);
      setBusy(false);
    }
  }

  return (
    <div className="signin">
      {/* Read in order, one beat apart. The form does not join in: a control
          that fades in is a control the hand has to wait for. */}
      <section className="signin-say">
        <h1 className="hero">
          <span className="reveal" style={{ animationDelay: "60ms" }}>
            환율은 기록하고,
          </span>
          <b className="reveal" style={{ animationDelay: "220ms" }}>
            판단은 남기세요
          </b>
        </h1>
        <p className="standfirst reveal" style={{ animationDelay: "430ms" }}>
          로그인하면 기업 정보를 반복해서 입력하지 않아도 같은 기준으로
          지원제도와 신고의무를 점검할 수 있습니다.
        </p>
        <ul className="signin-points reveal" style={{ animationDelay: "600ms" }}>
          <li>계정의 기업 사실을 분석에 일관되게 적용</li>
          <li>지원제도·신고의무 자동 점검</li>
          <li>계산은 결정론적 코드가 수행</li>
        </ul>
      </section>

      <form className="signin-card" onSubmit={submit}>
        <h2>로그인</h2>
        <p className="signin-sub">업무용 이메일로 계속하세요.</p>

        <label className="field" htmlFor="login-email">
          <span className="field-top">이메일</span>
          <input
            id="login-email"
            type="email"
            name="email"
            autoComplete="username"
            placeholder="name@company.co.kr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        <div className="field">
          <span className="field-top">
            <label htmlFor="login-password">비밀번호</label>
          </span>
          <span className="field-box">
            <input
              id="login-password"
              type={shown ? "text" : "password"}
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {/* Typing a password you cannot see is how a password gets typed
                twice. The toggle says what it will do, not what state it is
                in — "숨기기" while hidden reads as a claim that it already is. */}
            <button
              type="button"
              className="peek"
              onClick={() => setShown((v) => !v)}
              aria-pressed={shown}
            >
              {shown ? "숨기기" : "표시"}
            </button>
          </span>
        </div>

        {error && (
          <p className="signin-error" role="alert">
            {error}
          </p>
        )}

        <button className="signin-go" type="submit" disabled={busy}>
          {busy ? "확인하는 중" : "로그인"}
        </button>

        <p className="or"><span>또는</span></p>

        {/* The two ways a Korean SME actually signs in to something like this.
            Disabled rather than removed: they are what belongs here, and a
            button that looks live and goes nowhere is a worse promise than one
            that says it is not ready. */}
        <button className="signin-alt" type="button" disabled title="준비 중">
          회사 SSO로 로그인
        </button>
        <button className="signin-alt" type="button" disabled title="준비 중">
          공동인증서로 로그인
        </button>

        <p className="signin-legal">
          현재 관리자가 발급한 데모 계정만 지원합니다.
        </p>
      </form>
    </div>
  );
}
