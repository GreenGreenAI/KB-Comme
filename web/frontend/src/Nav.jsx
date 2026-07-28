import { useEffect, useRef, useState } from "react";

/** Kept in step with the .menu transition in styles.css. */
const MENU_EXIT_MS = 150;

/** Signed out shows a way in; signed in shows who you are. The menu is built
 *  from this product's own concepts — what is saved here is what the intake
 *  agent no longer has to ask for.
 *
 *  The screen opens signed in. There is no authentication yet and no sign-in
 *  page to send anyone to, so a button offering one would lead nowhere; the
 *  state worth showing is the one the rest of the product is designed around,
 *  where the company's own facts are already known. The signed-out branch is
 *  kept rather than deleted — it is what the real sign-in page will return to,
 *  and the menu's 로그아웃 still reaches it. */
export default function Nav({ onHome }) {
  const [signedIn, setSignedIn] = useState(true);
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

      <div className="account" ref={box}>
        {!signedIn ? (
          <button className="nav-cta" type="button" onClick={() => setSignedIn(true)}>
            로그인
          </button>
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
              한
            </button>
            {/* Entering and leaving are separate animations rather than one
                transition between classes. A transition needs the element to
                paint in its start state before the class flips, which means
                waiting for a frame; mounting straight into an animation does
                not. */}
            {mounted && (
              <div className={`menu ${open ? "" : "out"}`}>
                <div className="menu-id">
                  <span className="avatar" aria-hidden="true">한</span>
                  <div>
                    <b>한빛정밀</b>
                    <span>중소기업 · 제조업</span>
                  </div>
                </div>
                <a href="#">저장한 분석 <em>4건</em></a>
                <a href="#" className="saved">기업 정보 <em>3개 항목 저장됨</em></a>
                <a href="#">근거 이력 <em>스냅샷 12건</em></a>
                <p className="note">
                  중소기업 여부·담보 여력·업종은 계정에 저장되어 있어, 새 분석에서
                  다시 묻지 않습니다.
                </p>
                <hr />
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault();
                    setOpen(false);
                    setSignedIn(false);
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
