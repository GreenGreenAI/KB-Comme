/** Navigation exposes only implemented surfaces. Authentication and saved
 * analyses stay out of the UI until a real persistence boundary exists. */
export default function Nav() {
  return (
    <header className="nav">
      <div className="brand">
        <i>T</i> TradeFlow
      </div>
      <nav aria-label="주요 영역">
        <span className="on">분석</span>
        <span>지원제도</span>
        <span>신고의무</span>
        <span>근거</span>
      </nav>
      <div className="account">
        <span className="nav-cta" aria-label="MVP 데모">
          MVP 데모
        </span>
      </div>
    </header>
  );
}
