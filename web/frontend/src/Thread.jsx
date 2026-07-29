import { useEffect, useMemo, useState } from "react";
import { won, pct } from "./api.js";

/** How an answer arrives: top to bottom, one part after the next.
 *
 *  Read as a budget rather than as scattered constants — the sentence writes
 *  itself, and the figures follow it down the card.
 *
 *  Every gap here is shorter than the fade it starts, and deliberately so. A
 *  part that finished arriving before the next one began would read as a
 *  series of separate pops; overlapping them means eight or nine words are
 *  always mid-fade, and the sentence washes in instead of clicking into place.
 */
const OPENING_MS = 120;
const WORD_MS = 52;
const BLOCK_MS = 165;
const ARRIVE_MS = 520;   // matches the .arrive animation in styles.css

/** How long after the last unit lands before the motion classes come off.
 *  A hair over the longest fade, so nothing is cut short. */
const FADE_MS = ARRIVE_MS + 60;

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
export default function Thread({ turns, busy, thinking, onArrived, threadRef }) {
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
            onArrived={onArrived}
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


function AgentTurn({ turn, live, first, previous, onArrived }) {
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
        {/* §4.2[1] wrote this, over the slots the reader found missing. The
            list is what the screen falls back to — three questions stacked at
            someone who said hello, which is what this replaced. */}
        {turn.ask.spoken ? (
          <p>{turn.ask.spoken}</p>
        ) : (
          turn.ask.questions.map((question) => (
            <p key={question}>{question}</p>
          ))
        )}
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

  // §4.2[9] wrote this one, and the server only kept it after checking that
  // every number in it came from a tool. When it is empty — no key, no network,
  // or a sentence that invented a figure — the turn assembles its own, which is
  // why that assembly stays here rather than being deleted as dead code.
  const line = result.summary
    ? [{ text: result.summary }]
    : sentence({
        first, market, swing, hedge, hedgeIsNew, tradesChanged, tradeCount,
        opened, unread,
      });
  const words = line.reduce((n, seg) => n + seg.text.split(" ").length, 0);
  const asksProfit = !hedge && hedgeInputs.length > 0;

  // The order the turn arrives in, as a gap before each unit: the sentence a
  // word at a time, then the blocks below it.
  //
  // The trace is not in here. It is a list of which tools ran, not part of the
  // answer, and staging it made the reader watch a receipt being printed
  // before the answer would start. It is simply there.
  const timeline = useMemo(() => {
    const gaps = [];
    for (let i = 0; i < words; i += 1) gaps.push(i === 0 ? OPENING_MS : WORD_MS);
    // card, band, folds, and the line that follows them
    const blocks = 2 + (result.market_scenario ? 1 : 0) + (asksProfit ? 1 : 0);
    for (let i = 0; i < blocks; i += 1) gaps.push(BLOCK_MS);
    return gaps;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [words, asksProfit]);

  const [shown, settled] = useCascade(timeline, live);
  // One switch for the whole turn: while it is arriving the parts carry the
  // motion class, and once it has settled they carry nothing.
  const arrive = settled ? "" : " arrive";

  // The turn knows when it has finished landing; nothing else can. Block count
  // depends on what the plan produced and the sentence length varies, so a
  // constant elsewhere would drift out of step with the cascade.
  useEffect(() => {
    if (!live || !onArrived) return undefined;
    if (shown < timeline.length) return undefined;
    const timer = setTimeout(onArrived, ARRIVE_MS);
    return () => clearTimeout(timer);
  }, [live, onArrived, shown, timeline.length]);

  return (
    <div className="turn agent">
      <span className="who">TradeFlow</span>

      {trace.length > 0 && (
        <div className="trace">
          {trace.map((name) => (
            <span className="ok" key={name}>
              {WORKER_LABEL[name] ?? name}
            </span>
          ))}
        </div>
      )}

      {/* The sentence arrives a word at a time. Written as segments rather than
          JSX so words can be mounted one by one; emphasis rides along on the
          segment. */}
      {shown > 0 && <Written segments={line} shown={shown} settled={settled} />}

      {shown > words && (
        <Answer result={result} order={order} shown={shown - words} arrive={arrive} />
      )}

      {/* Asked once, and only in words. The fields live in the bar above the
          composer so they stay reachable after the thread scrolls on. */}
      {asksProfit && shown >= timeline.length && (
        <p className={arrive.trim()}>
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

/** Reveals a turn one unit at a time.
 *
 *  Units are mounted as their turn comes rather than rendered up front and
 *  faded in. A delayed fade leaves the whole answer sitting on screen as a
 *  ghost before it arrives, which reads as a half-loaded page; nothing that
 *  has not arrived should be on screen at all.
 *
 *  Returns what has arrived and whether the turn has settled. Settling is what
 *  makes it safe for the motion to touch opacity at all: an animation that is
 *  applied but never advances holds its opening frame forever, and an opening
 *  frame at zero is an answer nobody can read. Once the fade has had its time
 *  the classes come off, so the content's resting state is plain visible text
 *  that no stalled animation can override. The clock decides this, not the
 *  animation — a suspended timeline would never report itself finished.
 */
function useCascade(delays, live) {
  const [shown, setShown] = useState(live ? 0 : delays.length);
  const [settled, setSettled] = useState(!live);

  useEffect(() => {
    if (!live) {
      setShown(delays.length);
      setSettled(true);
      return undefined;
    }
    // How many units are due at a given moment, read off the clock rather
    // than counted off by a chain of timers. A hidden tab throttles timers to
    // one a second; a chain would then spend twenty seconds dribbling out an
    // answer the reader has already come back to, while a clock reading
    // catches up to where it should be on the first tick.
    //
    // An interval and not requestAnimationFrame, for the same reason in its
    // harsher form: rAF does not run at all in a hidden tab, so an answer
    // driven by it would simply never arrive.
    const schedule = [];
    let due = 0;
    for (const gap of delays) {
      due += gap;
      schedule.push(due);
    }

    const start = performance.now();
    const done = due + FADE_MS;
    const tick = setInterval(() => {
      const elapsed = performance.now() - start;
      let count = 0;
      while (count < schedule.length && schedule[count] <= elapsed) count += 1;
      setShown(count);
      if (elapsed < done) return;
      setSettled(true);
      clearInterval(tick);
    }, 16);
    return () => clearInterval(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, delays.length]);

  return [shown, settled];
}

/** Words appearing in order, as if being written.
 *
 *  Only the words that have arrived are rendered. Rendering the whole sentence
 *  and fading the rest in put the finished line on screen before it was
 *  written, which is the one thing writing-in is meant to avoid.
 *
 *  Only the newest turn writes itself. Re-animating the history every time
 *  React re-renders would make the whole conversation flicker.
 */
function Written({ segments, shown, settled }) {
  let index = 0;
  const out = [];
  for (const [s, segment] of segments.entries()) {
    for (const word of segment.text.split(" ")) {
      if (index >= shown) break;
      // The space sits outside the box. Each word has to be an inline-block
      // for a transform to apply to it, and a trailing space inside an
      // inline-block collapses — the sentence would come out run together.
      out.push(
        <span className={segment.strong ? "w em" : "w"} key={`${s}-${index}`}>
          {word}
        </span>,
        " ",
      );
      index += 1;
    }
    if (index >= shown) break;
  }
  return <p className={settled ? "written" : "written writing"}>{out}</p>;
}


function Answer({ result, order, shown, arrive }) {
  // The card arrives with its first figures, not before them. Drawing the grey
  // box first left an empty panel waiting to be filled, which read as
  // something still loading rather than as an answer being written.
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
    // The figures ride inside the card's own arrival — a second animation on
    // them would stack transforms and make them drift twice.
    <div className={`answer${arrive}`}>
      <dl className="figrow">
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
        <p className="answer-note">
          상계될 것처럼 보이지만 결제일이 어긋나 <b>만기가 겹치는 금액은 0</b>입니다.
        </p>
      )}

      {market && shown > 1 && <RateBand market={market} hedge={hedge} arrive={arrive} />}

      {/* Sections follow the order §4.2[2]'s intent reading produced. */}
      {shown > (market ? 2 : 1) && (
        <div className={`folds${arrive}`}>
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
      )}
    </div>
  );
}

/** Where the rate can land by the last payment date, drawn to scale. */
function RateBand({ market, hedge, arrive }) {
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
    <div className={`rate${arrive}`}>
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
