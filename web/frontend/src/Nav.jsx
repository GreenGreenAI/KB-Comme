/** Navigation exposes only implemented surfaces. Authentication and saved
 * analyses stay out of the UI until a real persistence boundary exists.
 *
 * The four links jump to sections of the panel, so they are only offered once
 * there is a panel to jump into. Before that they are disabled rather than
 * hidden: the reader can see what the finished answer will contain. Rendering
 * them as inert text — which they were — made them look like navigation that
 * silently did nothing. */
const AREAS = [
  { id: "sec-analysis", label: "분석" },
  { id: "sec-support", label: "지원제도" },
  { id: "sec-compliance", label: "신고의무" },
  { id: "sec-evidence", label: "근거" },
];

export default function Nav({ ready = false }) {
  function jump(id) {
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <header className="nav">
      <div className="brand">
        <i>T</i> TradeFlow
      </div>
      <nav aria-label="주요 영역">
        {AREAS.map((area) => (
          <button
            type="button"
            key={area.id}
            className="nav-link"
            onClick={() => jump(area.id)}
            disabled={!ready}
          >
            {area.label}
          </button>
        ))}
      </nav>
      <div className="account">
        <span className="nav-cta" aria-label="MVP 데모">
          MVP 데모
        </span>
      </div>
    </header>
  );
}
