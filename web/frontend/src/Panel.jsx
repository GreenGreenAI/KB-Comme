import { Fragment } from "react";

import { won, pct } from "./api.js";

/** Mirrors tools/intent.DEFAULT_ORDER, used until a response arrives. */
const DEFAULT_ORDER = [
  "exposure",
  "market_scenario",
  "hedge",
  "support",
  "compliance",
];

/** The living document. Sections fill in as the conversation supplies what
 *  they need, and a locked section states what would unlock it — that is the
 *  intake policy in §4.2 made visible rather than described. */
export default function Panel({ result, pending, facts }) {
  const cash = result?.cashflow_analysis;
  const market = result?.market_scenario;
  const hedge = result?.hedge_analysis;
  const completed = result?.workers?.completed ?? [];
  const order = result?.execution_plan?.section_order ?? DEFAULT_ORDER;

  const sections = [
    Boolean(cash),
    Boolean(market),
    Boolean(hedge),
    completed.includes("support"),
    completed.includes("compliance"),
  ];
  const done = sections.filter(Boolean).length;

  return (
    <aside className="col panel">
      <div className="panel-head">
        <h2 className="panel-title">분석 결과</h2>
        <div className="progress">
          <span>
            {done} / {sections.length} 완료
          </span>
          <span className="pips">
            {sections.map((on, index) => (
              <i className={`pip ${on ? "on" : ""}`} key={index} />
            ))}
          </span>
        </div>
      </div>

      {!result && (
        <section className="sec locked">
          <div className="sec-head">
            <div>
              <p className="eyebrow">대기 중</p>
              <h3>거래를 알려주세요</h3>
            </div>
          </div>
          <p className="unlock">
            <b>금액 · 결제일 · 수출인지 수입인지</b> 세 가지만 있으면 노출과 환율
            범위를 바로 계산합니다.
          </p>
        </section>
      )}

      {result?.trade_timeline?.length > 0 && (
        <Understanding cases={result.trade_timeline} />
      )}

      {/* §4.2[2]'s third input, applied. The question moves a section to the
          front; it never removes one, so a reader who asked about the rate
          still meets their filing duty further down. Input confirmation stays
          first regardless — every section below it rests on that reading. */}
      {order.map((section) => {
        const card = {
          exposure: cash ? <Cashflow cash={cash} /> : null,
          market_scenario: market ? (
            <Market market={market} hedge={hedge} />
          ) : null,
          hedge: (
            <Hedge
              hedge={hedge}
              reason={result?.workers?.skipped?.hedge}
              requiredInputs={result?.required_inputs?.hedge ?? []}
            />
          ),
          support: <Support result={result} />,
          compliance: <Compliance result={result} />,
        }[section];
        return card ? <Fragment key={section}>{card}</Fragment> : null;
      })}

      {result && <Evidence result={result} />}
    </aside>
  );
}

const DIRECTION_LABEL = { export: "수출 · 받을 돈", import: "수입 · 낼 돈" };
const METHOD_LABEL = { tt: "T/T", lc: "L/C", dp: "D/P", da: "D/A" };

/** What the sentence was turned into, before anything is calculated from it.
 *
 *  Every figure below this card rests on this reading, and until now there was
 *  nowhere to see it. A misread date produced a confidently wrong answer with
 *  no visible cause. It is placed first for that reason: it is the premise,
 *  not a detail. */
function Understanding({ cases }) {
  return (
    <section className="sec">
      <div className="sec-head">
        <div>
          <p className="eyebrow">입력 확인</p>
          <h3>이렇게 이해했습니다</h3>
        </div>
        <span className="state done">거래 {cases.length}건</span>
      </div>

      <ul className="cases">
        {cases.map((item) => (
          <li key={item.case_id}>
            <span className={`dir ${item.direction}`}>
              {DIRECTION_LABEL[item.direction] ?? item.direction}
            </span>
            <span className="amt">
              {item.currency} {won(item.amount)}
            </span>
            <span className="when">{item.expected_payment_date}</span>
            <span className="how">
              {METHOD_LABEL[item.payment_method] ?? item.payment_method}
            </span>
          </li>
        ))}
      </ul>

      <p className="unlock">
        다르게 이해했다면 그대로 말씀해 주세요 — 예: <b>결제일은 12월 3일이에요</b>
      </p>
    </section>
  );
}


function Cashflow({ cash }) {
  const gap = cash.funding_gap?.[0]?.peak_amount;
  const net = cash.net_exposure?.[0]?.amount;
  const natural = cash.natural_hedge_amount?.[0]?.amount;
  const matched = cash.maturity_matched_amount?.[0]?.amount;

  return (
    <section className="sec" id="sec-analysis">
      <div className="sec-head">
        <div>
          <p className="eyebrow">현금흐름</p>
          <h3>지금 얼마나 노출되어 있나?</h3>
        </div>
        <span className="state done">계산 완료</span>
      </div>

      <div className="figs">
        <div className="fig">
          <span className="fig-l">순노출</span>
          <span className="fig-v">
            {Number(net) > 0 ? "+" : ""}
            {won(net)}
            <small> USD</small>
          </span>
          <span className="fig-s">{Number(net) > 0 ? "수취 초과" : "지급 초과"}</span>
        </div>
        <div className="fig">
          <span className="fig-l">최대 자금 공백</span>
          <span className={`fig-v ${Number(gap) > 0 ? "alarm" : ""}`}>
            {won(gap)}
            <small> USD</small>
          </span>
          <span className="fig-s">
            {Number(gap) > 0 ? "따로 마련해야 합니다" : "따로 마련할 자금 없음"}
          </span>
        </div>
        <div className="fig">
          <span className="fig-l">자연헤지 가능액</span>
          <span className="fig-v">
            {won(natural)}
            <small> USD</small>
          </span>
          <span className="fig-s">
            {Number(natural) > 0
              ? `그중 만기 충족 ${won(matched)}`
              : "반대방향 거래 없음"}
          </span>
        </div>
      </div>

      {Number(natural) > 0 && Number(matched) === 0 && (
        <p className="unlock">
          수취와 지급이 상계될 것처럼 보이지만 결제일이 어긋나 있어{" "}
          <b>만기가 겹치는 금액은 0</b>입니다.
        </p>
      )}

      <p className="basis">
        <b>통화</b> USD · <b>거래</b> {cash.events?.length ?? 0}건
      </p>
    </section>
  );
}

function Market({ market, hedge }) {
  const lower = Number(market.band_lower);
  const upper = Number(market.band_upper);
  const spot = Number(market.spot_rate);
  const be = hedge?.breakeven_rate ? Number(hedge.breakeven_rate) : null;

  const values = [lower, upper, spot, ...(be ? [be] : [])];
  const spread = Math.max(...values) - Math.min(...values);
  const pad = spread === 0 ? Math.max(Math.abs(spot) * 0.01, 1) : spread * 0.12;
  const min = Math.min(...values) - pad;
  const max = Math.max(...values) + pad;
  const at = (v) => ((v - min) / (max - min)) * 100;

  return (
    <section className="sec">
      <div className="sec-head">
        <div>
          <p className="eyebrow">시장 시나리오</p>
          <h3>환율이 어디까지 움직일 수 있나?</h3>
        </div>
        <span className="state done">계산 완료</span>
      </div>

      <div className="band">
        <div
          className="band-fill"
          style={{ left: `${at(lower)}%`, width: `${at(upper) - at(lower)}%` }}
        />
        <div className="band-mid" style={{ left: `${at(spot)}%` }} />
        <div className="tick up" style={{ left: `${at(spot)}%` }}>
          현재<b>{won(spot)}</b>
        </div>
        <div className="tick dn" style={{ left: `${at(lower)}%` }}>
          하단<b>{won(lower)}</b>
        </div>
        <div className="tick dn" style={{ left: `${at(upper)}%` }}>
          상단<b>{won(upper)}</b>
        </div>
        {be !== null && (
          <div className="tick up" style={{ left: `${at(be)}%` }}>
            손익분기<b>{won(be)}</b>
          </div>
        )}
      </div>

      <div className="figs">
        <div className="fig">
          <span className="fig-l">연환산 변동성</span>
          <span className="fig-v">{pct(market.volatility_annualized, 2)}</span>
        </div>
        {hedge && (
          <div className="fig">
            <span className="fig-l">적자 전환 확률</span>
            <span className={`fig-v ${hedge.loss_probability > 0.05 ? "alarm" : ""}`}>
              {pct(hedge.loss_probability, 2)}
            </span>
            <span className="fig-s">손익분기 {won(hedge.breakeven_rate)}원</span>
          </div>
        )}
      </div>

      <p className="basis">
        <b>기준환율</b> {won(market.spot_rate)}원 · <b>단위</b> {market.unit} ·{" "}
        <b>관측</b> {market.observation_days}영업일 ({market.observed_from} ~{" "}
        {market.observed_to}) · <b>신뢰수준</b> {pct(market.confidence_level, 0)} ·{" "}
        <b>기간</b> {market.horizon_business_days}영업일 · <b>드리프트</b>{" "}
        {market.drift} · <b>반올림</b> {market.rounding}
      </p>
    </section>
  );
}

/** A section that has nothing to show yet.
 *
 *  It still has to say why — a silently absent card would read as "no hedge
 *  needed" rather than "we refused to guess". But a full card header for one
 *  sentence spent 920px on 66 characters, so the reason is stated on one line
 *  and the space goes to the sections that have something in them. */
function Blocked({ eyebrow, title, state, reason, id }) {
  return (
    <section className="sec blocked" id={id}>
      <p className="blocked-head">
        <span className="eyebrow">{eyebrow}</span>
        <span className="blocked-title">{title}</span>
        <span className="state need">{state}</span>
      </p>
      <p className="blocked-why">{reason}</p>
    </section>
  );
}

function Hedge({ hedge, reason, requiredInputs }) {
  if (!hedge) {
    return (
      <Blocked
        eyebrow="손익 · 헤지"
        title="얼마나 헤지하면 되나?"
        state={requiredInputs.length > 0 ? "입력 필요" : "검토 필요"}
        reason={
          reason ??
          "검증된 헤지 수단과 가격 정보가 준비되면 손익 비교를 계산합니다."
        }
      />
    );
  }

  const label = {
    unhedged: "헤지하지 않음",
    optimal: "최소 필요 헤지",
    fully_hedged: "전액 헤지",
  };
  const head = { adverse: "불리", median: "현재 유지", favourable: "유리" };

  return (
    <section className="sec">
      <div className="sec-head">
        <div>
          <p className="eyebrow">손익 · 헤지</p>
          <h3>얼마나 헤지하면 되나?</h3>
        </div>
        <span className="state done">계산 완료</span>
      </div>

      {hedge.status === "HEDGE_INSUFFICIENT" ? (
        <>
          <p className="unlock">
            전액을 헤지해도 목표 이익을 지킬 수 없습니다. 임의의 비율을 제시하지
            않습니다.
          </p>
          <ul className="unlock">
            {hedge.alternatives.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="unlock">
          권유가 아니라 비교입니다. 헤지를 늘리면 나쁜 쪽이 올라가는 만큼 좋은
          쪽도 내려갑니다.
        </p>
      )}

      <div className="scroller">
        <table>
          <thead>
            <tr>
              <th scope="col">헤지 비율</th>
              {hedge.payoff_comparison[0]?.points.map((point) => (
                <th scope="col" key={point.label}>
                  {head[point.label]}
                  <span className="fig-s">{won(point.rate)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {hedge.payoff_comparison.map((row) => (
              <tr key={row.ratio} className={row.label === "optimal" ? "chosen" : ""}>
                <td>
                  {label[row.label]}
                  <span className="fig-s">{pct(row.ratio)}</span>
                </td>
                {row.points.map((point) => (
                  <td
                    key={point.label}
                    className={
                      row.label === "unhedged" && point.label === "adverse"
                        ? "alarm"
                        : ""
                    }
                  >
                    {won(point.profit)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="basis">
        <b>수단</b> {hedge.instrument_candidates[0]?.measure_id} ·{" "}
        <b>불리 시나리오</b> {won(hedge.adverse_rate)}원 (
        {pct(hedge.confidence_level, 0)} 분위수) · <b>제약</b> 헤지비율 0~100% ·{" "}
        <b>반올림</b> {hedge.profit_rounding}
      </p>
    </section>
  );
}

function Support({ result }) {
  const candidates = result?.support_candidates ?? [];
  const excluded = result?.excluded_candidates ?? [];
  const completed = result?.workers?.completed?.includes("support");
  const skipped = result?.workers?.skipped?.support;

  // §4.2[2] left it out of the plan. The reason names what would put it back,
  // which is more use than three cards of "정보 부족".
  if (!completed && skipped) {
    return (
      <Blocked
        id="sec-support"
        eyebrow="지원제도"
        title="쓸 수 있는 제도가 있나?"
        state="알려주시면 판정"
        reason={skipped}
      />
    );
  }

  return (
    <section className={`sec ${completed ? "" : "locked"}`} id="sec-support">
      <div className="sec-head">
        <div>
          <p className="eyebrow">지원제도</p>
          <h3>쓸 수 있는 제도가 있나?</h3>
        </div>
        <span className={`state ${completed ? "done" : "need"}`}>
          {completed ? "규칙 판정 완료" : "대기 중"}
        </span>
      </div>
      {completed ? (
        <>
          <p className="unlock">
            후보 {candidates.length}건 · 제외 {excluded.length}건. 초안 규칙이나
            근거가 부족한 결과는 전문가 확인 대상으로 유지합니다.
          </p>
          {candidates.map((candidate) => (
            <p className="basis" key={`${candidate.subject_id}:${candidate.rule_id}`}>
              <b>{candidate.title}</b> · {candidate.status}
            </p>
          ))}
        </>
      ) : (
        <p className="unlock">거래 정보가 준비되면 역할 A 규칙으로 판정합니다.</p>
      )}
    </section>
  );
}

function Compliance({ result }) {
  const findings = result?.risk_findings ?? [];
  const obligations = result?.filing_obligations ?? [];
  const completed = result?.workers?.completed?.includes("compliance");
  const skipped = result?.workers?.skipped?.compliance;

  return (
    <Blocked
      id="sec-compliance"
      eyebrow="규제"
      title="해야 할 신고가 있나?"
      state={completed ? "규칙 판정 완료" : "알려주시면 판정"}
      reason={
        completed
          ? `검토 항목 ${findings.length}건 · 실행 의무 후보 ${obligations.length}건. 정보가 부족한 항목은 신고 불필요로 간주하지 않습니다.`
          : (skipped ?? "거래 정보가 준비되면 역할 A 규칙으로 판정합니다.")
      }
    />
  );
}

const SNAPSHOT_LABELS = {
  ECOS_USD_KRW: "환율 스냅샷",
  KNOWLEDGE_SOURCES: "출처 검증",
};

const RULE_REASON = /^[A-Z0-9_-]+:[A-Z0-9_]+: \S+$/;

/** Why a human still has to look at this.
 *
 *  `review_reasons` carries two different things: sentences written for the
 *  reader ("환율 시나리오를 산출하지 못해…") and one entry per undecided rule,
 *  shaped `CASE:RULE_ID: status`. Joining all of them produced three thousand
 *  characters of identifiers in which the readable sentences were invisible.
 *
 *  The rules are not dropped — they are already listed by title in the 지원제도
 *  and 신고의무 cards above, which is where a reader can do something about
 *  them. Here they are counted. */
function ReviewReasons({ reasons }) {
  const readable = reasons.filter((item) => !RULE_REASON.test(item));
  const ruleCount = reasons.length - readable.length;

  return (
    <div className="review">
      <p className="review-head">
        <b>검토 필요</b>
      </p>
      {readable.map((item) => (
        <p className="review-item" key={item}>
          {item}
        </p>
      ))}
      {ruleCount > 0 && (
        <p className="review-item">
          규칙 {ruleCount}건이 정보 부족으로 확정되지 않았습니다. 어떤 규칙인지는
          위 <b>지원제도</b>·<b>신고의무</b>에 항목별로 나와 있습니다.
        </p>
      )}
    </div>
  );
}


function Evidence({ result }) {
  const market = result.evidence.find((item) => item.role === "market_data");
  const versions = result.calculation_versions ?? {};
  const rulepacks = (versions.knowledge_files ?? []).filter(
    (item) => item.role === "rulepack"
  );
  return (
    <section className="sec" id="sec-evidence">
      <div className="sec-head">
        <div>
          <p className="eyebrow">근거</p>
          <h3>이 숫자는 어디서 왔나?</h3>
        </div>
        <span className="state done">추적 가능</span>
      </div>
      <p className="basis" style={{ borderTop: "none", paddingTop: 0 }}>
        {market && (
          <>
            <b>환율</b> 한국은행 ECOS · <b>계산</b> {versions.formula_version} ·{" "}
          </>
        )}
        <b>규칙</b> {rulepacks.length}개 규칙팩
      </p>

      {/* The full input identity is what a replay has to match, but it is
          reference material — open when someone is checking, folded when they
          are reading the answer. */}
      <details className="fold">
        <summary>재현에 필요한 입력</summary>
        <ul className="versions">
          {(versions.snapshots ?? []).map((item) => (
            <li key={item.source_id}>
              <span className="vk">
                {SNAPSHOT_LABELS[item.source_id] ?? item.source_id}
              </span>
              <span className="vv">{item.version}</span>
            </li>
          ))}
          {rulepacks.map((item) => (
            <li key={item.path}>
              <span className="vk">규칙팩</span>
              <span className="vv">{item.path.split("/").pop()}</span>
            </li>
          ))}
          {versions.input_fingerprint && (
            <li>
              <span className="vk">입력 지문</span>
              <span className="vv mono">
                {versions.input_fingerprint.replace("sha256:", "").slice(0, 16)}…
              </span>
            </li>
          )}
        </ul>
        <p className="fold-note">
          이 넷이 모두 같아야 같은 답이 나옵니다. 하나라도 다르면 재현이 아니라
          다른 계산입니다.
        </p>
      </details>

      {result.review_required && <ReviewReasons reasons={result.review_reasons} />}
    </section>
  );
}
