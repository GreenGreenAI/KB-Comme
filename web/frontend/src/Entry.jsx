import { useEffect, useState } from "react";

import { health } from "./api.js";

const STARTERS = [
  "10월 24일에 수출대금 10만 달러 받기로 했어요",
  "8월 25일에 수입대금 6만 달러 나가요",
  "12월 3일에 $150,000 수취 예정입니다",
  "3월 20일 수입 20만 달러 결제해요",
];

export default function Entry({ onSend, busy }) {
  const [text, setText] = useState("");

  // The badge names the data the next answer will actually be built on, so it
  // is read from the server rather than written into the page. A hardcoded
  // date here silently became a false claim the day the snapshot moved.
  const [asOf, setAsOf] = useState(null);
  useEffect(() => {
    let alive = true;
    health()
      .then((info) => {
        const versions = info.fx_snapshots ?? [];
        if (alive && versions.length) setAsOf(versions[versions.length - 1]);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  function submit(value) {
    const trimmed = (value ?? text).trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
  }

  return (
    <div className="entry-wrap">
      <span className="badge">
        <em>연동</em> 한국은행 ECOS 매매기준율
        {asOf ? ` · ${asOf} 기준` : ""}
      </span>

      <h1 className="hero">
        짐작하지 말고
        <br />
        <b>계산하세요</b>
      </h1>
      <p className="standfirst">
        수출입 거래의 환위험을 한국은행 환율로 계산하고, 출처와 기준일까지 함께
        보여드립니다. 환율을 예측하지는 않습니다.
      </p>

      <div className="prompt">
        <textarea
          rows="2"
          value={text}
          placeholder="거래를 편하게 설명해 주세요. 예: 10월 24일에 수출대금 10만 달러 받기로 했어요"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="prompt-foot">
          <div className="toggles">
            <span className="toggle"><i /> 근거 표시</span>
            <span className="toggle off"><i /> 상세 계산</span>
          </div>
          <button
            className="send"
            type="button"
            onClick={() => submit()}
            disabled={busy}
            aria-label="분석 시작"
          >
            ↑
          </button>
        </div>
      </div>

      <div className="chips">
        {STARTERS.map((starter) => (
          <button
            key={starter}
            className="chip"
            type="button"
            onClick={() => submit(starter)}
          >
            {starter}
          </button>
        ))}
      </div>

      <p className="assurance">
        금액 계산과 규정 판정은 모두 결정론적 코드가 수행합니다. AI는 묻고 설명할
        뿐, 수치를 만들지 않습니다.
      </p>
    </div>
  );
}
