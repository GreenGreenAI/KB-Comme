import { useState } from "react";

/** The way in.
 *
 *  Two halves that say different things. The left says why an account is worth
 *  having — and it says it in this product's own terms: what is kept is the
 *  calculation and the rate it used, not "your data". The right is the form,
 *  and it is deliberately dull. A sign-in box is somewhere the hand goes, not
 *  somewhere the eye lingers.
 *
 *  Nothing here authenticates. There is no account system behind this yet, so
 *  the form does not send what is typed anywhere — it changes the screen. The
 *  fields are real controls rather than a picture so the layout is honest
 *  about the space a password manager and an error message will need, but a
 *  box that collected credentials and quietly dropped them would be worse than
 *  no box at all.
 */
export default function Login({ onSignIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [remember, setRemember] = useState(true);

  function submit(event) {
    event.preventDefault();
    onSignIn();
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
          로그인하면 계산한 거래와 적용된 한국은행 기준환율, 기준일이 그대로
          보관됩니다. 신고의무 확인 결과도 함께 남습니다.
        </p>
        <ul className="signin-points reveal" style={{ animationDelay: "600ms" }}>
          <li>거래 내역과 산출 근거 보관</li>
          <li>지원제도·신고의무 자동 점검</li>
          <li>계산은 결정론적 코드가 수행</li>
        </ul>
      </section>

      <form className="signin-card" onSubmit={submit}>
        <h2>로그인</h2>
        <p className="signin-sub">업무용 이메일로 계속하세요.</p>

        <label className="field">
          <span className="field-top">이메일</span>
          <input
            type="email"
            name="email"
            autoComplete="username"
            placeholder="name@company.co.kr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        <label className="field">
          <span className="field-top">
            비밀번호
            <a href="#" onClick={(e) => e.preventDefault()}>잊으셨나요?</a>
          </span>
          <span className="field-box">
            <input
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
        </label>

        <label className="check">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          <span className="tickbox" aria-hidden="true" />
          로그인 상태 유지
        </label>

        <button className="signin-go" type="submit">
          로그인
        </button>

        <p className="or"><span>또는</span></p>

        {/* The two ways a Korean SME actually signs in to something like this.
            They are here because they are the real alternatives, not to fill
            the space — and neither is wired up yet. */}
        <button className="signin-alt" type="button" onClick={onSignIn}>
          회사 SSO로 로그인
        </button>
        <button className="signin-alt" type="button" onClick={onSignIn}>
          공동인증서로 로그인
        </button>

        <p className="signin-legal">
          로그인하면 <a href="#" onClick={(e) => e.preventDefault()}>이용약관</a>과{" "}
          <a href="#" onClick={(e) => e.preventDefault()}>개인정보 처리방침</a>에
          동의하는 것으로 봅니다.
        </p>
      </form>
    </div>
  );
}
