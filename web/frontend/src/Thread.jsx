import { useEffect, useState } from "react";
import { won, pct } from "./api.js";

/** How an answer arrives: top to bottom, one part after the next.
 *
 *  Read as a budget rather than as scattered constants — the trace lands
 *  first, the sentence writes itself, and the figures follow it down the
 *  card. Nothing starts from nothing: every part opens at 0.2 so an animation
 *  that never advances costs the motion and not the content.
 */
const TRACE_MS = 70;
const WORD_MS = 45;
const AFTER_SENTENCE_MS = 90;
const BLOCK_MS = 130;

const DEFAULT_ORDER = [
  "exposure",
  "market_scenario",
  "hedge",
  "support",
  "compliance",
];

const WORKER_LABEL = {
  exposure: "순노출·자금공백 산출",
  source_verification: "공식 출처 검증 확인",
  market_scenario: "변동성 추정 — 최근 60영업일",
  hedge: "헤지비율 산출",
  support: "지원제도 규칙 판정",
  compliance: "신고의무 규칙 판정",
};

/** The conversation, including the trace of which tools actually ran. That
 *  trace is not decoration: it is how a reader can tell the figures came from
 *  a calculation rather than from the model's prose. */
export default function Thread({ turns, busy, thinking, threadRef }) {
  return (
    <div className="thread" ref={threadRef}>
      {turns.length === 0 && !busy && (
        <div className="turn agent">
          <span className="who">TradeFlow</span>
          <p>거래를 알려주시면 계산을 시작합니다.</p>
        </div>
      )}

      {turns.map((turn, index) =>
        turn.who === "user" ? (
          <div className="turn user" key={index}>
            <span className="who">나</span>
            <div className="said">{turn.text}</div>
          </div>
        ) : (
          <AgentTurn
            key={index}
            turn={turn}
            live={index === turns.length - 1 && !busy}
            first={!turns.slice(0, index).some((t) => t.kind === "result")}
            previous={
              turns
                .slice(0, index)
                .filter((t) => t.kind === "result")
                .at(-1)?.result ?? null
            }
          />
        ),
      )}

      {busy && <Thinking thinking={thinking} />}
    </div>
  );
}

const STEP_LABEL = {
  exposure: "순노출·자금공백 산출",
  source_verification: "공식 출처 검증 확인",
  market_scenario: "변동성 추정",
  support: "지원제도 규칙 판정",
  compliance: "신고의무 규칙 판정",
  hedge: "헤지비율 산출",
  synthesis: "답변 정리",
  read: "문장에서 거래 정보 읽기",
  slots: "빠진 정보 확인",
  placement: "앞 거래와 대조",
};

/** What the agent is doing, while it is doing it.
 *
 *  One line at a time: the step in progress replaces the one before it. A
 *  growing list drew the eye back to work already finished and pushed the
 *  conversation up the screen while the reader was waiting. What the answer
 *  was built from is not lost — the trace under the finished answer carries
 *  the same list.
 *
 *  Before an answer is in hand there is no plan to show, so the indicator
 *  falls back to a single line. It appears after a short delay either way, so
 *  a fast exchange never flashes one.
 */
function Thinking({ thinking }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), 180);
    return () => clearTimeout(timer);
  }, []);

  if (!visible) return null;

  const steps = thinking?.steps ?? [];
  const active = thinking?.index ?? 0;

  return (
    <div className="turn agent thinking" aria-live="polite">
      <span className="who">TradeFlow</span>
      {steps.length === 0 ? (
        <p className="think">
          <Dots />
          계산하고 있습니다
        </p>
      ) : (
        <p className="step" key={steps[active]}>
          <Dots />
          {STEP_LABEL[steps[active]] ?? steps[active]}
        </p>
      )}
    </div>
  );
}

function Dots() {
  return (
    <span className="dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  );
}


function AgentTurn({ turn, live, first, previous }) {
  if (turn.kind === "error") {
    return (
      <div className="turn agent">
        <span className="who">TradeFlow</span>
        <p>{turn.text}</p>
      </div>
    );
  }

  if (turn.kind === "placement") {
    return (
      <div className="turn agent">
        <span className="who">TradeFlow</span>
        <Understood heard={turn.ask.understood} />
        <p>{turn.ask.question}</p>
      </div>
    );
  }

  if (turn.kind === "ask") {
    return (
      <div className="turn agent">
        <span className="who">TradeFlow</span>
        <Understood heard={turn.ask.understood} />
        {turn.ask.issues?.map((issue) => (
          <p key={issue.field}>{issue.reason}</p>
        ))}
        {turn.ask.questions.map((question) => (
          <p key={question}>{question}</p>
        ))}
      </div>
    );
  }

  const result = turn.result;
  const market = result.market_scenario;
  const hedge = result.hedge_analysis;
  const swing = market?.adverse_cashflow_amount ?? null;
  const hedgeInputs = result.required_inputs?.hedge ?? [];
  const order = result.execution_plan?.section_order ?? DEFAULT_ORDER;

  // Only what this turn changed. Re-rendering the full trace every turn made
  // three exchanges carry eighteen identical lines, and the repetition buried
  // the one line that was actually new.
  const before = new Set(previous?.workers?.completed ?? []);
  const opened = result.workers.completed.filter((name) => !before.has(name));
  const trace = first ? result.workers.completed : opened;
  const tradeCount = result.trade_timeline?.length ?? 0;
  const tradesChanged =
    previous !== null && tradeCount !== (previous.trade_timeline?.length ?? 0);
  const hedgeIsNew = Boolean(hedge) && !previous?.hedge_analysis;
  // The sentence was sent, nothing was read out of it, and nothing moved.
  // Saying "다시 계산했습니다" here claims work that did not happen.
  const unread =
    turn.spoken &&
    Object.keys(turn.heard ?? {}).length === 0 &&
    !first &&
    !tradesChanged &&
    opened.length === 0;

  const line = sentence({
    first, market, swing, hedge, hedgeIsNew, tradesChanged, tradeCount,
    opened, unread,
  });
  const words = line.reduce((n, seg) => n + seg.text.split(" ").length, 0);
  const sentenceStart = trace.length * TRACE_MS;
  const answerStart = sentenceStart + words * WORD_MS + AFTER_SENTENCE_MS;

  return (
    <div className="turn agent">
      <span className="who">TradeFlow</span>

      {trace.length > 0 && (
        <div className="trace">
          {trace.map((name, index) => (
            <span
              className={`ok ${live ? "arrive" : ""}`}
              style={{ animationDelay: `${index * TRACE_MS}ms` }}
              key={name}
            >
              {WORKER_LABEL[name] ?? name}
            </span>
          ))}
        </div>
      )}

      {/* The sentence arrives a word at a time, after the trace has landed.
          Written as segments rather than JSX so each word can carry its own
          delay; emphasis rides along on the segment. */}
      <Written live={live} segments={line} start={sentenceStart} />

      <Answer result={result} order={order} live={live} start={answerStart} />

      {/* Asked once, and only in words. The fields live in the bar above the
          composer so they stay reachable after the thread scrolls on. */}
      {!hedge && hedgeInputs.length > 0 && live && (
        <p>
          기준 영업이익과 회사가 지키려는 목표 손익 하한을 각각 입력해 주세요.
          입력하지 않은 하한을 임의로 만들지 않습니다.
        </p>
      )}
    </div>
  );
}

const SECTION_LABEL = {
  exposure: "노출",
  market_scenario: "환율",
  hedge: "헤지",
  support: "지원제도",
  compliance: "신고의무",
};

/** The figures, inside the message that produced them.
 *
 *  They used to live in a side panel. Moving them here keeps one reading
 *  order: the answer is where the answer was asked for, and an older turn's
 *  numbers stay attached to the question that produced them instead of being
 *  overwritten by the next one.
 *
 *  Only the headline figures are open. Everything else is a fold — this is a
 *  chat message, and a message that takes four screens is not one. */
/** The agent's line for this turn, as segments. */
function sentence({ first, market, swing, hedge, hedgeIsNew, tradesChanged, tradeCount, opened, unread }) {
  if (first && market && swing !== null) {
    const direction =
      market.adverse_cashflow_direction === "decrease" ? "적어집니다" : "많아집니다";
    return [
      { text: "계산했습니다." },
      { text: `결제일까지 불리한 환율이 ${won(market.adverse_rate)}원일 수 있고,`, strong: true },
      { text: "그러면 받는 금액이 지금보다" },
      { text: `${won(swing)}원 ${direction}.`, strong: true },
    ];
  }
  if (hedgeIsNew) {
    return [
      { text: "손익분기 환율은" },
      { text: `${won(hedge.breakeven_rate)}원`, strong: true },
      { text: "이고, 최소" },
      { text: pct(hedge.optimal_ratio), strong: true },
      { text: "만 헤지하면 목표 이익을 지킬 수 있습니다." },
    ];
  }
  if (tradesChanged) return [{ text: `거래 ${tradeCount}건으로 다시 계산했습니다.` }];
  if (opened.length > 0) {
    return [{ text: `${opened.map((n) => WORKER_LABEL[n] ?? n).join(" · ")}까지 채웠습니다.` }];
  }
  if (unread) {
    return [{
      text: "그 문장에서는 거래 정보를 읽지 못해 계산이 달라지지 않았습니다. " +
            "금액 · 결제일 · 수출입 여부는 문장으로 알려주실 수 있습니다.",
    }];
  }
  return [{ text: "다시 계산했습니다." }];
}

/** Merge a base class with the arrival props, so a block can have both. */
function withClass(props, base) {
  return { ...props, className: [base, props.className].filter(Boolean).join(" ") };
}

/** Words appearing in order, as if being written.
 *
 *  They fade in from dim rather than from nothing. An animation that is
 *  applied but not advancing holds its opening frame, and a sentence whose
 *  opening frame is invisible is a sentence that can fail to arrive. At 0.2 it
 *  is faint but readable, so the worst case costs the effect and not the text.
 *
 *  Only the newest turn writes itself. Re-animating the history every time
 *  React re-renders would make the whole conversation flicker.
 */
function Written({ segments, live, start = 0 }) {
  let index = 0;
  return (
    <p className={live ? "written" : ""}>
      {segments.map((segment, s) =>
        segment.text.split(" ").map((word) => {
          const i = index;
          index += 1;
          return (
            <span
              className={`w ${segment.strong ? "em" : ""}`}
              style={{ animationDelay: `${start + i * WORD_MS}ms` }}
              key={`${s}-${i}`}
            >
              {word}{" "}
            </span>
          );
        })
      )}
    </p>
  );
}


function Answer({ result, order, live, start = 0 }) {
  // Each block of the card follows the one above it.
  let block = 0;
  const next = () => {
    const delay = start + block * BLOCK_MS;
    block += 1;
    return live
      ? { className: "arrive", style: { animationDelay: `${delay}ms` } }
      : {};
  };
  const cash = result.cashflow_analysis;
  const market = result.market_scenario;
  const hedge = result.hedge_analysis;
  if (!cash) return null;

  const net = cash.net_exposure?.[0]?.amount;
  const gap = cash.funding_gap?.[0]?.peak_amount;
  const natural = cash.natural_hedge_amount?.[0]?.amount;
  const matched = cash.maturity_matched_amount?.[0]?.amount;
  const skipped = result.workers?.skipped ?? {};

  return (
    <div className="answer">
      <dl {...withClass(next(), "figrow")}>
        <div>
          <dt>순노출</dt>
          <dd>
            {Number(net) > 0 ? "+" : ""}
            {won(net)} <small>USD</small>
          </dd>
        </div>
        <div>
          <dt>자금 공백</dt>
          <dd className={Number(gap) > 0 ? "alarm" : ""}>
            {won(gap)} <small>USD</small>
          </dd>
        </div>
        <div>
          <dt>자연헤지</dt>
          <dd>
            {won(natural)} <small>USD</small>
          </dd>
        </div>
      </dl>

      {Number(natural) > 0 && Number(matched) === 0 && (
        <p {...withClass(next(), "answer-note")}>
          상계될 것처럼 보이지만 결제일이 어긋나 <b>만기가 겹치는 금액은 0</b>입니다.
        </p>
      )}

      {market && <RateBand market={market} hedge={hedge} wrap={next()} />}

      {/* Sections follow the order §4.2[2]'s intent reading produced. */}
      <div {...withClass(next(), "folds")}>
        {order
          .filter((section) => section !== "exposure" && section !== "market_scenario")
          .map((section) => {
            const reason = skipped[section === "hedge" ? "hedge" : section];
            if (section === "hedge" && hedge) {
              return (
                <details className="fold" key={section}>
                  <summary>
                    헤지 · 손익분기 {won(hedge.breakeven_rate)}원 · 최소{" "}
                    {pct(hedge.optimal_ratio)}
                  </summary>
                  <p className="fold-note">
                    적자 전환 확률 {pct(hedge.loss_probability, 1)} · 불리한 환율{" "}
                    {won(hedge.adverse_rate)}원 기준
                  </p>
                </details>
              );
            }
            if (!reason) return null;
            return (
              <details className="fold" key={section}>
                <summary>{SECTION_LABEL[section]} · 알려주시면 판정</summary>
                <p className="fold-note">{reason}</p>
              </details>
            );
          })}

        <details className="fold">
          <summary>근거 · 재현에 필요한 입력</summary>
          <ul className="versions">
            {(result.calculation_versions?.snapshots ?? []).map((item) => (
              <li key={item.source_id}>
                <span className="vk">{item.source_id}</span>
                <span className="vv">{item.version}</span>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}

/** Where the rate can land by the last payment date, drawn to scale. */
function RateBand({ market, hedge, wrap = {} }) {
  const lower = Number(market.band_lower);
  const upper = Number(market.band_upper);
  const spot = Number(market.spot_rate);
  const be = hedge?.breakeven_rate ? Number(hedge.breakeven_rate) : null;

  // The track spans the band exactly, so the numbers printed at each end are
  // the numbers at each end. Padding is added only to bring a breakeven rate
  // that falls outside the band into view — otherwise the labels would sit
  // where the band does not reach.
  const outside = be !== null && (be < lower || be > upper);
  const span = upper - lower || Math.max(Math.abs(spot) * 0.01, 1);
  const pad = outside ? span * 0.12 : 0;
  const min = Math.min(lower, ...(outside ? [be] : [])) - pad;
  const max = Math.max(upper, ...(outside ? [be] : [])) + pad;
  const at = (v) => ((v - min) / (max - min)) * 100;

  return (
    <div {...withClass(wrap, "rate")}>
      <div className="rate-track">
        <span
          className="rate-fill"
          style={{ left: `${at(lower)}%`, width: `${at(upper) - at(lower)}%` }}
        />
        <span className="rate-now" style={{ left: `${at(spot)}%` }} />
        {be !== null && (
          <span className="rate-be" style={{ left: `${at(be)}%` }} />
        )}
      </div>
      <p className="rate-legend">
        <span>{won(lower)}</span>
        <b>현재 {won(spot)}</b>
        <span>{won(upper)}</span>
      </p>
      <p className="answer-note">
        {market.horizon_business_days}영업일 · 신뢰 {pct(market.confidence_level, 0)}{" "}
        · 변동성 {pct(market.volatility_annualized, 2)} · 드리프트 0 고정
      </p>
    </div>
  );
}

function Understood({ heard }) {
  if (!heard || Object.keys(heard).length === 0) return null;
  const parts = [];
  if (heard.direction) parts.push(heard.direction);
  if (heard.amount) parts.push(`${won(heard.amount)} USD`);
  if (heard.expected_payment_date) parts.push(heard.expected_payment_date);
  return <p>{parts.join(" · ")}로 이해했습니다.</p>;
}
