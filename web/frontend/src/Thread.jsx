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
  exposure: "거래 순노출·자금공백 산출",
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
          <span className="who">KB Comme</span>
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
            live={
              // `restored` marks a turn that came back from storage rather
              // than from the server. It has been read once already, and
              // replaying the write-out on a refresh would make the page look
              // like it was answering a question nobody asked.
              index === turns.length - 1 && !busy && !turn.restored
            }
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
  exposure: "거래 순노출·자금공백 산출",
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
      <span className="who">KB Comme</span>
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
        <span className="who">KB Comme</span>
        <p>{turn.text}</p>
      </div>
    );
  }

  if (turn.kind === "placement") {
    return (
      <div className="turn agent">
        <span className="who">KB Comme</span>
        <Understood heard={turn.ask.understood} />
        <p>{turn.ask.question}</p>
      </div>
    );
  }

  if (turn.kind === "said") {
    // Nothing was computed for this turn and nothing is folded away beneath
    // it. What the server sent is the whole answer, so it is set as prose —
    // the answer blocks below belong to a decision and there is none here.
    return (
      <div className="turn agent">
        <span className="who">KB Comme</span>
        {turn.ask.spoken
          ?.split("\n\n")
          .map((block) => (
            <p className="prose" key={block}>
              {block}
            </p>
          ))}

        {/* What we do not do about this subject, before what we want from
            them. A company that asked what a scheme is should learn that we
            do not answer that before being asked for an amount. */}
        {turn.ask.cannot && <p className="told quiet">{turn.ask.cannot}</p>}

        {/* Still owed. The subject may have had a part that holds on its own
            — today's rate does — and a part that needs the trade. Saying so
            is what stops the reader waiting for the rest. */}
        {turn.ask.asks_for_trade && <p>{turn.ask.asks_for_trade}</p>}

        {turn.ask.holds && <p className="pointer lead">{turn.ask.holds}</p>}
        {turn.ask.coverage && (
          <p className="pointer limit">{turn.ask.coverage}</p>
        )}
      </div>
    );
  }

  if (turn.kind === "ask") {
    return (
      <div className="turn agent">
        <span className="who">KB Comme</span>
        <Understood heard={turn.ask.understood} />
        {turn.ask.issues?.map((issue) => (
          <p key={issue.field}>{issue.reason}</p>
        ))}
        {/* What the product holds for the money they just described, before
            what it still needs. Not a limit, so not set as one — folded into
            the grey block below it read as a footnote to its own subject.

            Above the question because it is the answer: a company that asked
            which loan it could get should be told there is one before being
            told what we want from them. */}
        {turn.ask.holds && <p className="pointer lead">{turn.ask.holds}</p>}

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

        {/* Most sessions stop on this turn, so the limits of what was asked
            about belong here too — not only on an answer the reader may never
            reach. */}
        {turn.ask.coverage && (
          <p className="pointer limit">{turn.ask.coverage}</p>
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
  //
  // Not for a follow-up. 「왜?」 states nothing and was not trying to; telling
  // its author that no trade information could be read out of it answers a
  // sentence they did not write.
  const unread =
    turn.spoken &&
    !result.follows &&
    Object.keys(turn.heard ?? {}).length === 0 &&
    !first &&
    !tradesChanged &&
    opened.length === 0;

  // §4.2[9] wrote this one, and the server only kept it after checking that
  // every number in it came from a tool. When it is empty — no key, no network,
  // or a sentence that invented a figure — the turn assembles its own, which is
  // why that assembly stays here rather than being deleted as dead code.
  // What closes the answer. The rewrite when there is one — it is the version
  // that has read every judgement — and §4.2[9]'s own sentence otherwise.
  // Both are paragraphs and both get cut to the sentence carrying the figure;
  // everything after it has already been said above, beside its evidence.
  const summary = result.said?.retold || result.summary;
  const line = summary
    ? [{ text: recap(summary) }]
    : sentence({
        first, market, swing, net: result.cashflow_analysis?.net_exposure?.[0]?.amount,
        hedge, hedgeIsNew, tradesChanged, tradeCount, opened, unread,
      });
  const words = line.reduce((n, seg) => n + seg.text.split(" ").length, 0);
  // Which of the two opens the answer, decided by the server from the intent
  // §4.2[2] already read. Absent — an older turn, or a trade description with
  // no question in it — keeps the sentence first.
  const leads = result.lead === "pointer";
  // The order the turn arrives in, as a gap before each unit: the sentence a
  // word at a time, then the blocks below it.
  //
  // The trace is not in here. It is a list of which tools ran, not part of the
  // answer, and staging it made the reader watch a receipt being printed
  // before the answer would start. It is simply there.
  const tail = trailing(result, order).length;
  // The figures, the band when there is one, then each part below them on its
  // own step — 규칙이 확인한 것, 손익 비교, 건너뛴 이유, 근거 used to share one,
  // so the answer was written a word at a time and everything under it landed
  // on a single frame.
  const blocks = 1 + (result.market_scenario ? 1 : 0) + tail;
  const timeline = useMemo(() => {
    const gaps = [];
    // Blocks first, sentence last. The summary is now what closes the answer
    // rather than what opens it, and an arrival order that still typed it out
    // first would be the old reading order surviving the layout change — the
    // reader would watch a conclusion appear before anything supporting it.
    for (let i = 0; i < blocks; i += 1) gaps.push(BLOCK_MS);
    for (let i = 0; i < words; i += 1) gaps.push(i === 0 ? OPENING_MS : WORD_MS);
    return gaps;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [words, blocks]);

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
      <span className="who">KB Comme</span>

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
      {/* What we do not do about the subject they raised, before anything we
          do. A company that asked what a scheme is met a request for its size
          and its credit standing, and never learned that the question had no
          answer here. */}
      {result.cannot && <p className="told">{result.cannot}</p>}

      {/* Written by code, not by §4.2[9]: the sentence is about the figures,
          and this says what else the answer holds. Counts only — every verdict
          is rendered from its own worker's output below.

          It goes above the sentence when the question was not about what the
          sentence can say. Someone who asked about 제작 자금 met their
          exchange-rate exposure first, every time, because the synthesised
          sentence may only quote figures and every figure is an exposure. The
          server decides which; nothing here re-reads the question. */}
      {leads && shown > 0 && result.pointer && (
        <p className={`pointer lead${arrive}`}>{result.pointer}</p>
      )}

      {!leads && shown > 0 && result.pointer && (
        <p className={`pointer${arrive}`}>{result.pointer}</p>
      )}

      {/* What the subject they raised is not covered by. Nothing above is
          false without it; what is missing is the sentence that stops the
          reader waiting for an answer that is not coming. */}
      {shown > 0 && result.holds && (
        <p className={`pointer lead${arrive}`}>{result.holds}</p>
      )}

      {shown > 0 && result.coverage && (
        <p className={`pointer limit${arrive}`}>{result.coverage}</p>
      )}

      {/* Moved, not shrunk. It is not an answer to a question about what a
          scheme is and must not lead — but it is a figure the tools computed,
          and §2's reader does not know their own exposure. Set small and grey
          it wore the style the limits wear, and a computed amount read as a
          disclaimer: the demotion meant to keep it visible was removing it.

          Demotion is position here, not size. Same rule as 답·맥락·감사. */}
      {shown > 0 && result.cannot && !result.said?.retold && (
        <p className="told">{line.map((seg) => seg.text).join(" ")}</p>
      )}

      {shown > 0 && (
        <Answer result={result} order={order} shown={shown} arrive={arrive} />
      )}

      {/* The summary, last and once. It used to open the answer and it packed
          five assertions into five sentences — the exposure, three verdicts
          and a document count — with the grounds for every one of them in a
          fold underneath all five. Read in that order the reader met the
          conclusions before anything that supported them, and could only check
          one by leaving the paragraph.
          Now the blocks above have said each of those things beside its own
          evidence, so what is left for this line to do is be the one sentence
          somebody repeats afterwards. `recap` keeps it to that. */}
      {shown > blocks && !result.cannot && (
        <div className="recap">
          <Written segments={line} shown={shown - blocks} settled={settled} />
          {/* The largest number in the answer was the only claim with nothing
              under it. Every rule judgement could at least be opened; the
              figure most likely to be repeated to a bank could not say where
              it came from. */}
          {settled && result.basis && <p className="ground-row">{result.basis}</p>}
        </div>
      )}

      {/* §4.2[2]의 이유는 여기 다시 쓰지 않습니다. 바로 아래 요청 패널이
          같은 값을 묻고 있고, 그 위에 「기준 영업이익을 알려주시면 …」이 서면
          같은 요청이 연달아 두 번입니다 — 오늘 로그인 안내에서 걷어낸 것과
          같은 모양입니다. 이유는 패널의 부제로 들어갔습니다. */}
    </div>
  );
}

/** What a rule concluded, in the words a person uses for it.
 *
 *  §5.4 and §5.5 report five outcomes and the screen must keep them apart
 *  (PR #51 AC-6). Collapsing "아직 못 정했다" into "해당 없다" is the single
 *  most dangerous thing this screen could do: one is a question, the other is
 *  a clearance, and a company that reads the second when the first was meant
 *  ships without filing.
 */
const PAYOFF_LABEL = {
  unhedged: "헤지하지 않으면",
  fully_hedged: "전액 헤지하면",
  recommended: "권장 비율로",
};

const POINT_LABEL = { adverse: "불리", median: "중앙", favourable: "유리" };

/** What each choice is worth at three rates.
 *
 *  §5.3 computes this and it was going unread. The comparison is the answer to
 *  "지금 환전해 두는 게 나을까요" — not a ratio, but what the same trade earns
 *  under each decision, at a rate nobody is predicting.
 */
function Payoff({ hedge }) {
  const rows = hedge.payoff_comparison ?? [];
  if (rows.length === 0) return null;
  const points = rows[0].points ?? [];
  return (
    <table className="payoff">
      <thead>
        <tr>
          <th />
          {points.map((point) => (
            <th key={point.label}>
              {POINT_LABEL[point.label] ?? point.label}
              <small>{won(point.rate)}</small>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <th scope="row">{PAYOFF_LABEL[row.label] ?? row.label}</th>
            {(row.points ?? []).map((point) => (
              <td key={point.label}>{won(point.profit)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Which quote the ratio rests on. A number that cannot say where its price
 *  came from is the thing §5.3 refuses to produce. */
function QuoteBasis({ hedge }) {
  const used = (hedge.instrument_candidates ?? []).filter(
    (item) => item.status === "available",
  );
  if (used.length === 0) return null;
  return (
    <p className="sources">
      {used.map((item) => item.measure_id).join(" · ")}
    </p>
  );
}

const STATUS_LABEL = {
  expert_confirmation_required: "전문가 확인 필요",
  insufficient_information: "정보 부족",
  matched: "조건 충족",
  not_matched: "조건 불충족",
  source_expired: "출처 만료",
};

const FACT_LABEL = {
  "company.size": "기업규모",
  "company.credit_issue_free": "신용 이슈 여부",
  "company.ksure_exporter_grade": "K-SURE 수출자 등급",
  "counterparty.ksure_importer_grade": "수입자 등급",
  "counterparty.country_restricted": "상대국 인수 제한 여부",
  "trade.payment_term_days": "결제기간",
  "financing.purpose": "자금 용도",
  "financing.has_bank_consultation": "은행 상담 여부",
  "payment.is_netting": "상계 여부",
  "payment.netting.party_count": "상계 당사자 수",
  "payment.netting.uses_center": "상계센터 경유 여부",
  "payment.netting.smaller_claim_usd": "상계하는 채권·채무 중 작은 금액",
  "payment.netting.exception_category": "상계 신고예외 유형",
  "payment.is_third_party": "제3자 지급 여부",
  "payment.third_party.amount_usd": "제3자 지급 금액",
  "payment.third_party.exception_category": "제3자 지급 신고예외 유형",
  "payment.uses_mutual_account": "상호계산 사용 여부",
  "payment.uses_foreign_exchange_bank": "외국환은행 경유 여부",
  "payment.direction": "지급·수령 방향",
  "payment.nonbank.exception_category": "비은행 지급 신고예외 유형",
};

/** The object particle, chosen the way Korean chooses it.
 *
 *  `을(를)` is what a template writes when it does not know the word it is
 *  about to join, and the missing-facts line joins a different word every
 *  time. A final consonant decides this, and a syllable carries one at a fixed
 *  offset — so it can simply be read rather than sidestepped. */
function particle(word) {
  const last = word.trim().slice(-1).charCodeAt(0);
  const syllable = last >= 0xac00 && last <= 0xd7a3;
  return syllable && (last - 0xac00) % 28 !== 0 ? "을" : "를";
}

const AUTHORITY_LABEL = {
  ksure: "한국무역보험공사",
  bok: "한국은행",
  bank: "지정거래외국환은행",
};

/** §5.4 support, once it has actually judged something.
 *
 *  This used to render `null`. The fold only drew a line when the worker had
 *  been skipped, so completing the judgement made it disappear — the better
 *  the analysis did, the less the screen said. Three candidates were being
 *  decided on every signed-in request and none of them reached the user.
 */
function Support({ result, open }) {
  const candidates = result.support_candidates ?? [];
  const excluded = result.excluded_candidates ?? [];
  if (candidates.length === 0 && excluded.length === 0) {
    return (
      <details className="fold" open={open}>
        <summary>지원제도 · 해당하는 제도 없음</summary>
        <p className="fold-note">
          규칙을 모두 확인했고 이 거래에 해당하는 제도가 없었습니다. 판정하지
          못한 것과는 다릅니다.
        </p>
      </details>
    );
  }
  const settled = candidates.filter((c) => c.status !== "insufficient_information");
  return (
    <details className="fold" open={open}>
      <summary>
        지원제도 · 후보 {settled.length}건
        {candidates.length - settled.length > 0 &&
          ` · 정보 부족 ${candidates.length - settled.length}건`}
        {excluded.length > 0 && ` · 제외 ${excluded.length}건`}
      </summary>
      {candidates.map((candidate) => (
        <Candidate key={candidate.rule_id} candidate={candidate} />
      ))}
      {excluded.map((candidate) => (
        <Candidate key={candidate.rule_id} candidate={candidate} excluded />
      ))}
    </details>
  );
}

/** What a verdict means, said rather than labelled.
 *
 *  A chip reading 「전문가 확인 필요」 tells a company nothing it can act on:
 *  does it qualify or not? These say what happened and what is left, which is
 *  the same information the status carries and the only form of it a reader
 *  can use. */
const VERDICT_LINE = {
  expert_confirmation_required:
    "조건은 모두 맞습니다. 초안 규칙이라 공식 확인을 받으셔야 합니다.",
  matched: "조건을 모두 충족합니다.",
  not_matched: "이 거래에는 해당하지 않습니다.",
  source_expired: "근거로 쓴 출처가 만료되어 판정을 보류했습니다.",
};

const CHECK_MARK = { passed: "✓", uncertain: "?", failed: "✗" };

function Candidate({ candidate, excluded }) {
  const missing = candidate.missing_fields ?? [];
  // The rule's own conditions, in the words the rulepack wrote them in. The
  // comparison that produced each one stays one fold deeper — nobody should
  // have to read `company.size=small in [...]` to learn what was checked,
  // and nobody auditing one should be unable to.
  const checks = candidate.checks ?? [];
  const verdict = excluded
    ? VERDICT_LINE.not_matched
    : VERDICT_LINE[candidate.status];

  return (
    <div className="verdict">
      <div className="verdict-head">
        <b>{candidate.title}</b>
      </div>
      {verdict && <p className="fold-note">{verdict}</p>}
      {missing.length > 0 && (
        <p className="fold-note">
          {(() => {
            const words = missing.map((f) => FACT_LABEL[f] ?? f);
            return `${words.join(" · ")}${particle(words[words.length - 1])} 알려주시면 판정합니다.`;
          })()}
        </p>
      )}
      {checks.length > 0 && (
        <ul className="checks">
          {checks.map((check) => (
            <li className={check.status} key={check.field + check.description}>
              <span className="check-mark">{CHECK_MARK[check.status] ?? "·"}</span>
              {check.description}
            </li>
          ))}
        </ul>
      )}
      {/* The conditions as the rule wrote them. Summary first, the rule's own
          text one fold deeper (AC-5): nobody should have to read
          `company.size=small in [...]` to learn that a judgement was made, and
          nobody checking one should be unable to. */}
      {candidate.sources?.length > 0 && (
        <ul className="cites">
          {candidate.sources.map((source) => (
            <li key={source.source_id}>
              {source.url ? (
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.title}
                </a>
              ) : (
                source.title
              )}
              {source.organization && <em>{source.organization}</em>}
            </li>
          ))}
        </ul>
      )}

      {/* The comparisons as the engine made them. A count is not a citation,
          and this fold is where the audit lives — not where the answer does. */}
      <details className="why">
        <summary>이 판정을 만든 비교 {candidate.reasons?.length ?? 0}건</summary>
        <ul className="reasons">
          {(candidate.reasons ?? []).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="sources">{(candidate.source_ids ?? []).join(" · ")}</p>
      </details>
    </div>
  );
}

/** §5.5 compliance, once it has judged.
 *
 *  An empty list here is never "신고 불필요". §5.5 only raises a duty from a
 *  trade structure the company states, so silence means the structures we
 *  asked about were not present — not that nothing else could apply.
 */
function Compliance({ result, open }) {
  const obligations = result.filing_obligations ?? [];
  // Every §5.5 rule that ran and was not ruled out. `filing_obligations` is
  // the subset that produced an action, so a rule saying "정보가 부족합니다"
  // appeared nowhere — and the fold went on announcing 확인된 신고 사유 없음
  // while seventeen rules were waiting to be told something. One is a
  // question, the other is a clearance.
  const findings = (result.risk_findings ?? []).filter(
    (f) => f.outcome?.kind !== "support_candidate",
  );
  // The company said 상계, so the netting rules know they apply and are
  // waiting on which authority. The rest do not know whether they apply at
  // all. Showing both as one list buries the three that answer the question.
  const engaged = findings.filter((f) => f.engaged);
  const rest = findings.filter((f) => !f.engaged);

  if (obligations.length === 0 && findings.length === 0) {
    return (
      <details className="fold">
        <summary>신고의무 · 확인된 신고 사유 없음</summary>
        <p className="fold-note">
          알려주신 거래 구조에서는 신고 사유가 확인되지 않았습니다. 신고가
          불필요하다는 판정은 아닙니다.
        </p>
      </details>
    );
  }
  return (
    <details className="fold" open={open || engaged.length > 0}>
      <summary>
        신고의무 · {engaged.length > 0 ? `해당 ${engaged.length}건` : `검토 ${findings.length}건`}
      </summary>
      {obligations.map((item) => (
        <Candidate key={item.rule_id} candidate={item} />
      ))}
      {engaged.map((item) => (
        <Candidate key={item.rule_id} candidate={item} />
      ))}
      {rest.length > 0 && (
        <details className="why">
          <summary>말씀해 주신 것으로는 해당 여부를 알 수 없는 규칙 {rest.length}건</summary>
          {rest.map((item) => (
            <Candidate key={item.rule_id} candidate={item} />
          ))}
        </details>
      )}
    </details>
  );
}

/** What each row of evidence is evidence *of*. Two words, because a reader
 *  scanning down the blocks needs to tell at a glance which side of a
 *  judgement a line is on — and 「확인」 beside 「필요」 does that where a bare
 *  bullet list does not. */
const GROUND_LABEL = { met: "확인", wanted: "필요", ours: "저희 몫" };

/** The documents are not conditions. 「필요」 above a list of forms reads as
 *  facts the reader is being asked for, which is the one thing this screen
 *  must never blur — a form to bring and a fact still missing are different
 *  kinds of unfinished. */
const ACTION_GROUND_LABEL = { met: "확인", wanted: "서류", ours: "저희 몫" };

/** One claim with its grounds directly beneath it.
 *
 *  Every sentence here was already on screen and so was every row under it —
 *  the sentences ran together as one paragraph and the rows sat in a fold
 *  below all of them. Nothing is new; what changed is that a claim and the
 *  thing that supports it are now in the same place, which is the only
 *  arrangement in which either is worth showing.
 *
 *  The rows are a line, not a list. Five conditions set as five bullets is the
 *  record this product spent its time turning into sentences, arriving back in
 *  a different shape.
 */
function Grounded({ block }) {
  const labels = block.kind === "action" ? ACTION_GROUND_LABEL : GROUND_LABEL;
  // 「저희 몫」 last: it is the only row that asks nothing of the reader, and
  // putting it above what they can act on makes them read past it.
  const rows = ["met", "wanted", "ours"].filter(
    (side) => (block[side] ?? []).length > 0,
  );
  return (
    <div className={`ground ${block.kind}${block.settled === false ? " open" : ""}`}>
      <p className="ground-claim">{block.claim}</p>
      {rows.map((side) => (
        <p className={`ground-row ${side}`} key={side}>
          <span className="ground-label">{labels[side]}</span>
          {block[side].join(" · ")}
        </p>
      ))}
    </div>
  );
}

/** What the person reading this has to go and do.
 *
 *  The product's output is not a number, it is a trade decision plan. Every
 *  scenario this was designed against ends the same way — who, by when, with
 *  which documents — and all of it was already in the response, unused.
 */
function Actions({ actions }) {
  if (!actions || actions.length === 0) return null;
  return (
    <details className="fold" open>
      <summary>다음 행동 · {actions.length}건</summary>
      {actions.map((action, index) => (
        <div className="verdict" key={`${action.action}-${index}`}>
          <div className="verdict-head">
            <b>{ACTION_LABEL[action.action] ?? action.action}</b>
            <span className="chip who">
              {AUTHORITY_LABEL[action.authority] ?? action.authority}
            </span>
          </div>
          <p className="fold-note">
            {TIMING_LABEL[action.timing] ?? action.timing}
            {action.deadline ? ` · 기한 ${action.deadline}` : ""}
          </p>
          {(action.required_documents ?? []).length > 0 && (
            <details className="why">
              <summary>필요서류 {action.required_documents.length}건</summary>
              <ul className="reasons">
                {action.required_documents.map((doc) => (
                  <li key={doc}>{doc}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      ))}
    </details>
  );
}

const ACTION_LABEL = {
  consult_and_apply_for_ksure_product: "K-SURE 상품 상담 및 청약",
};

const TIMING_LABEL = {
  before_application: "청약 전",
  before_shipment: "선적 전",
  before_payment: "결제 전",
};

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
/** The synthesised paragraph, kept to the sentence worth repeating.
 *
 *  §4.2[9] writes one paragraph per turn and it grows with the analysis: a
 *  turn that judged three products and produced two errands came back as five
 *  assertions in a row, every one of them also stated — with its evidence —
 *  in the blocks above. Read together they are the same answer twice, and the
 *  copy without grounds was the one that led.
 *
 *  Cutting it here rather than asking the model for less: the guard that
 *  checks every figure against a tool runs on the whole paragraph, and a
 *  shorter prompt would have moved that check, not kept it. What survives is
 *  the first sentence, which is where §4.2[9] puts the figure.
 */
function recap(summary) {
  // The stop has to be followed by something for the sentence to have ended:
  // 「100,000 USD」 and 「1,441.1원」 carry stops of their own, and splitting on
  // every one of them leaves 「최대 10,188」.
  const sentences = String(summary).trim().split(/(?<=[.。])\s+/u);
  const kept = [];
  for (const line of sentences) {
    // Cutting at the first sentence was wrong and it lost the figure. §4.2[9]
    // writes the calculation first and the verdicts after, but how many
    // sentences the calculation takes is the model's to decide — one turn
    // opened 「100,000 USD 결제가 결제일까지 열려 있습니다」 and put the
    // 10,188,000 in the sentence after it. So the cut is made where the
    // subject changes rather than after a fixed count.
    if (JUDGEMENT.test(line)) break;
    kept.push(line);
    if (kept.length === RECAP_MAX) break;
  }
  // A summary that names a scheme in its first sentence still has to say
  // something. One sentence of overlap beats an empty close.
  return (kept.length > 0 ? kept : sentences.slice(0, 1)).join(" ");
}

/** A sentence that has moved on to the verdicts — which the blocks above have
 *  already given, each beside the conditions it rests on. */
const JUDGEMENT = /K-SURE|보험|보증|신고|서류|상담|제도/u;

/** Two at the outside. The recap is what somebody repeats afterwards, and
 *  nobody repeats a paragraph. */
const RECAP_MAX = 2;

/** The agent's line for this turn, as segments. */
function sentence({ first, market, swing, net, hedge, hedgeIsNew, tradesChanged, tradeCount, opened, unread }) {
  if (first && market && swing !== null) {
    // Which way the money moves is the trade's, not the sentence's. This said
    // 받는 금액 whatever the direction was, so an import — where a rising rate
    // means paying more — was told its receipts had fallen. §4.2[9]'s own
    // sentence has derived this from the sign since it was written; only this
    // fallback, the one shown when the model is unavailable, did not.
    // The direction the server sends is the *cashflow's*, and for a payer the
    // amount paid moves against it: a net KRW cashflow that falls by 3,573,600
    // is an importer paying that much more. Naming the noun without turning
    // the verb produced 「내는 금액이 적어집니다」 on a rising rate — fluent,
    // and the opposite of what happened to the company.
    const receiving = Number(net) > 0;
    const worse = market.adverse_cashflow_direction === "decrease";
    const noun = receiving ? "받는 금액" : "내는 금액";
    const direction = receiving === worse ? "적어집니다" : "많아집니다";
    return [
      { text: "계산했습니다." },
      { text: `결제일까지 불리한 환율이 ${won(market.adverse_rate)}원일 수 있고,`, strong: true },
      { text: `그러면 ${noun}이 지금보다` },
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


/** The exposure card, folded when the question was about something else.
 *
 *  Folded rather than dropped. `intent.js`'s rule — 의도는 답의 순서를 정하지
 *  범위를 좁히지 않는다 — is why: §2's reader does not know their own exposure,
 *  and a company asking about 상계 still has 60,000 USD open. Rendering
 *  nothing would mean they never learn it. So the judgement they asked for
 *  opens, and the calculation waits one click away with its headline figure
 *  in the summary. */
function Calculation({ folded, children, net }) {
  if (!folded) return children;
  return (
    <details className="fold calc">
      <summary>환노출 · 거래 순노출 {won(net)} USD</summary>
      {children}
    </details>
  );
}

/** What comes after the figures, in the order it arrives — one key per part.
 *
 *  The parts used to be one block behind one condition, so four unrelated
 *  things — 규칙이 확인한 것, 손익 비교, 건너뛴 워커의 이유, 근거, 재현 입력 —
 *  landed on the same frame. The answer above them arrives a word at a time and
 *  then everything under it appeared at once, which reads as a page that was
 *  already written rather than one being written.
 *
 *  Counted here rather than in either caller: the turn needs the number to size
 *  its cascade and the answer needs the list to render, and the two drifting
 *  apart would show as a part that never arrives or a pause with nothing in it. */
function trailing(result, order) {
  const said = result.said ?? {};
  const skipped = result.workers?.skipped ?? {};
  const folded = result.lead === "pointer";
  const asked = folded
    ? order.find((s) => s !== "exposure" && s !== "market_scenario")
    : null;
  const rest = order.filter(
    (s) => s !== "exposure" && s !== "market_scenario" && s !== asked,
  );

  const parts = [];
  if (said.detail?.length > 0) parts.push("detail");
  if (result.hedge_analysis) parts.push("payoff");
  for (const section of rest) {
    if (!skipped[section]) continue;
    if (asked || result.asking_for === section) continue;
    parts.push(`skipped:${section}`);
  }
  if (said.sources?.length > 0) parts.push("sources");
  // 「재현에 필요한 입력」은 화면에 없습니다. §6.2가 요구하는 것은 같은 분석이
  // 같은 패킷을 내는 것이고, 그 근거는 응답의 `calculation_versions`와
  // `packet_id`가 계속 싣고 있습니다 — 스냅샷 판 번호를 읽는 사람은 화면이
  // 아니라 그 응답을 보는 사람입니다.
  return parts;
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
  // The same signal that puts the judgement above the sentence: the question
  // was about something the exposure card does not answer.
  const folded = result.lead === "pointer";
  // The section the question was about, if it was about one of these. It
  // opens; a judgement that was asked for and arrives collapsed is the same
  // failure as one rendered below the exchange rate — the reader has to go
  // looking for the answer to their own question.
  const asked = folded
    ? order.find((s) => s !== "exposure" && s !== "market_scenario")
    : null;
  // Everything the question did not raise, in the plan's order.
  const rest = order.filter(
    (s) => s !== "exposure" && s !== "market_scenario" && s !== asked,
  );
  const said = result.said ?? {};
  // The parts below the figures, and how many of them have arrived. The first
  // step after the figures (and the band, when there is one) brings the first
  // part; each step after that brings one more.
  const parts = trailing(result, order);
  const here = Math.max(0, shown - (market ? 2 : 1));
  //: A part arrives with the motion the rest of the turn arrives with, and
  //: only on the step it belongs to. `at` is that test, written once.
  const at = (key) => parts.indexOf(key) > -1 && parts.indexOf(key) < here;
  const step = (key) => (parts.indexOf(key) === here - 1 ? arrive.trim() : "");
  // Whether this turn's answer is sentences. When it is, the card is dropped:
  // the box exists to hold a figure grid, and the grid is folded away.
  // The card is the figure grid and the band. Prose never belonged inside it —
  // sentences in a grey box read as a document handed over, not an answer
  // given, which is the impression the folds were removed to stop.
  // The same judgements with their grounds attached. `spoken` remains the
  // fallback for a turn the server answered before this field existed — a
  // restored session carries whatever the response held at the time, and a
  // blank block is worse than an ungrounded sentence.
  //
  // `retold` does not disable this, and briefly it did. The rewrite is the
  // one path that only runs when there is a key, so switching the blocks off
  // for it meant the whole change was invisible in the only build anyone was
  // looking at — and what it renders instead is precisely the paragraph the
  // blocks exist to break up: every judgement merged into one, none of them
  // near its evidence. It belongs in the recap, not above the answer.
  const grounded = said.grounded ?? [];
  const spoken =
    grounded.length > 0
      ? []
      : said.retold
        ? [said.retold]
        : [
            ...(said.support ?? []),
            ...(said.compliance ?? []),
            ...(said.actions ?? []),
          ];

  return (
    // The figures ride inside the card's own arrival — a second animation on
    // them would stack transforms and make them drift twice.
    <>
    {/* Said first, and outside the card. When the rewrite landed it already
        carries the figures sentence, so the one above is the same claim twice
        — three lines apart, in the same words. */}
    {/* Asked for. These are the conditions each rule checked, and they live in
        a fold until somebody says 「왜?」 — at which point the thing they asked
        for being one click away is the same as not answering. First, because
        the question was 「왜」 and this is the answer to it. */}
    {(result.because ?? []).map((line) => (
      <p className="told" key={line}>
        {line}
      </p>
    ))}

    {grounded.length > 0
      ? grounded.map((block, index) => (
          <Grounded block={block} key={`${block.kind}-${index}`} />
        ))
      : spoken.map((line) => (
          <p className="told" key={line}>
            {line}
          </p>
        ))}

    <div className={`answer${arrive}`}>
      <Calculation folded={folded} net={net}>
        <>
          {/* A zero is a result and it is not news. On a single export all
              three columns but the first read 0, and two thirds of the grid
              said nothing while taking the same room as the figure that did.
              The zeros are stated below in one line, so nothing is hidden and
              nothing is repeated at full size. */}
          <dl className="figrow">
            <div>
              {/* 「거래」가 붙는 이유는 이것이 세는 것이 거래뿐이기 때문입니다.
                  명세 §5.1의 `E`는 보유 외화까지 더하지만, 이 값은
                  Σ수취 − Σ지급이고 §5.1의 검증값(잔여노출)이 붙어 있는 쪽입니다.
                  보유 외화를 넣은 사람에게 두 값이 갈리므로, 이름이 무엇을
                  세었는지 말해야 합니다. */}
              <dt>거래 순노출</dt>
              <dd>
                {Number(net) > 0 ? "+" : ""}
                {won(net)} <small>USD</small>
              </dd>
            </div>
            {Number(gap) > 0 && (
              <div>
                <dt>자금 공백</dt>
                <dd className="alarm">
                  {won(gap)} <small>USD</small>
                </dd>
                {/* 금액만 있는 공백은 걱정이고, 날짜가 붙은 공백은 할 일입니다.
                    8월 25일에 6만 달러가 있느냐 없느냐는 숫자만 보아서는 알 수
                    없고, 그 날짜는 응답의 타임라인에 이미 있었습니다. */}
                {result.funding_window?.said && (
                  <dd className="when">{result.funding_window.said}</dd>
                )}
              </div>
            )}
            {/* 큰 자리에는 실제로 덮이는 금액이 섭니다.
                전에는 「기간 상쇄」가 여기 있었는데, 그 값은 전체 기간의 유입과
                유출이 겹치는 몫일 뿐 결제일까지 맞물리는지는 보지 않습니다.
                자금 공백 60,000 옆에 기간 상쇄 60,000이 같은 크기로 서면 같은
                숫자가 두 번 보이고, 하나는 진짜 부담이고 하나는 덮이지 않는
                착시입니다 — 그리고 「실제로는 0」은 각주에 있었습니다.
                가장 큰 활자가 가장 오해하기 쉬운 값이었습니다. */}
            {Number(natural) > 0 && (
              <div>
                <dt>실제로 덮이는 금액</dt>
                <dd className={Number(matched) === 0 ? "faded" : ""}>
                  {won(matched)} <small>USD</small>
                </dd>
              </div>
            )}
          </dl>

          {(Number(gap) === 0 || Number(natural) === 0) && (
            <p className="answer-note">
              {Number(gap) === 0 && "결제일에 모자라는 외화는 없습니다."}
              {Number(gap) === 0 && Number(natural) === 0 && " "}
              {Number(natural) === 0 &&
                "상쇄될 반대 방향 거래도 없습니다."}
            </p>
          )}

          {/* 상쇄가 있으면 그중 실제로 덮이는 몫을 늘 말합니다. 전에는 0일
              때만 각주가 붙어서, 6만이 절반만 덮이는 경우에는 화면에 6만만
              남았습니다 — 둘 중 하나만 보이면 읽는 사람은 그것을 덮인 금액으로
              읽습니다. */}
          {Number(natural) > 0 && (
            <p className="answer-note">
              {Number(matched) === 0 ? (
                <>
                  전 기간으로는 <b>{won(natural)} USD</b>가 상쇄되지만, 결제일이
                  어긋나 자금으로는 덮이지 않습니다.
                </>
              ) : Number(matched) < Number(natural) ? (
                <>
                  전 기간 상쇄는 <b>{won(natural)} USD</b>이고, 그중 결제일이
                  맞물리는 만큼만 자금으로 덮입니다.
                </>
              ) : (
                <>
                  전 기간 상쇄 <b>{won(natural)} USD</b>가 결제일까지 맞물립니다.
                </>
              )}
            </p>
          )}

          {market && shown > 1 && (
            <RateBand market={market} hedge={hedge} arrive={arrive} />
          )}
        </>
      </Calculation>

      {/* Three tiers, not six equal rows. The section the question was about
          is the answer and stands on its own; the ones nobody asked about are
          one folded line together; the audit is the last line.

          Before this every section — 환노출, 헤지, 신고의무, 지원제도 — sat in
          one grey card at the same size, the same colour and the same indent,
          so the screen said nothing about which of them was the answer. §2's
          protection is unchanged: everything is still one click away. It just
          no longer takes the same room as the thing that was asked for. */}
      {/* One part per step, in `trailing`'s order. `here` is how many of them
          have arrived; each renders only once its own step has come. */}
      {parts.length > 0 && here > 0 && (
        <div className="folds">
        {/* The judgements, said. Assembled server-side from what the rules
            decided and the words the rulepack wrote its conditions in — the
            same information the folds held, in the shape a person reads.

            What stays visual is what a sentence is the wrong shape for: the
            band above (a position on a scale) and the payoff table (three
            choices at three rates). A picture of a number is worse than the
            number. */}
        {/* §4.2[9] retold these when it could do so without adding or dropping
            anything; otherwise they arrive as assembled. §5.5's 「신고가
            불필요하다는 판정은 아닙니다」 goes in as a phrase the rewrite must
            carry word for word — it is not that compliance cannot be retold,
            it is that one sentence in it cannot be reworded. */}
        {at("detail") && (
          <details className={`fold aside ${step("detail")}`}>
            <summary>규칙이 확인한 것과 필요서류</summary>
            {/* Keyed by position, not by title. Two errands at the same
                authority each contribute a row called 「필요서류」, and React
                drops the second of two children sharing a key — the document
                list for the second errand simply was not rendered. */}
            {said.detail.map((row, index) => (
              <div className="verdict" key={`${row.title}-${index}`}>
                <div className="verdict-head">
                  <b>{row.title}</b>
                </div>
                <ul className="checks">
                  {row.met.map((word) => (
                    <li className="passed" key={word}>
                      <span className="check-mark">✓</span>
                      {word}
                    </li>
                  ))}
                  {row.wanted.map((word) => (
                    <li className="uncertain" key={word}>
                      <span className="check-mark">?</span>
                      {word}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </details>
        )}

        {at("payoff") && (
          <div className={step("payoff")}>
            <Payoff hedge={hedge} />
          </div>
        )}

        {/* Skipped workers still say why, in one line each. */}
        {rest
          .filter((section) => at(`skipped:${section}`))
          .map((section) => (
            <p className={`told quiet ${step(`skipped:${section}`)}`} key={section}>
              {skipped[section]}
            </p>
          ))}

        {at("sources") && (
          <p className={`told quiet ${step("sources")}`}>
            근거:{" "}
            {said.sources.map((source, index) => (
              <span key={source.source_id}>
                {index > 0 && " · "}
                {source.url ? (
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.title}
                  </a>
                ) : (
                  source.title
                )}
              </span>
            ))}
          </p>
        )}

        </div>
      )}
    </div>
    </>
  );

  function renderSection(section) {
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
                  <Payoff hedge={hedge} />
                  <QuoteBasis hedge={hedge} />
                </details>
              );
            }
            // A worker that did not run says why. One that ran says what it
            // found — including that it found nothing, which is a different
            // answer and must not wear the same words.
            if (reason) {
              return (
                <details className="fold" key={section}>
                  <summary>{SECTION_LABEL[section]} · 알려주시면 판정</summary>
                  <p className="fold-note">{reason}</p>
                </details>
              );
            }
            if (section === "support") {
              return <Support key={section} result={result} open={section === asked} />;
            }
            if (section === "compliance") {
              return (
                <Compliance key={section} result={result} open={section === asked} />
              );
            }
            return null;
  }
}

/** Where the rate can land by the last payment date, drawn to scale. */
function RateBand({ market, hedge, arrive }) {
  const lower = Number(market.band_lower);
  const upper = Number(market.band_upper);
  const spot = Number(market.spot_rate);
  const be = hedge?.breakeven_rate ? Number(hedge.breakeven_rate) : null;
  // Which end is the bad one. The band drawn without it is a range with no
  // direction: an exporter loses on the left and an importer on the right, and
  // the reader has to work that out from a sentence three lines above. The
  // adverse rate is already computed — §5.2 picks the end the trade suffers at
  // — so the drawing can simply say which one it was.
  const adverse = market.adverse_rate ? Number(market.adverse_rate) : null;
  const adverseIsLow = adverse !== null && Math.abs(adverse - lower) < Math.abs(adverse - upper);

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
        {adverse !== null && (
          <span
            className={`rate-adverse ${adverseIsLow ? "low" : "high"}`}
            style={
              adverseIsLow
                ? { left: `${at(min)}%`, width: `${at(adverse) - at(min)}%` }
                : { left: `${at(adverse)}%`, width: `${at(max) - at(adverse)}%` }
            }
          />
        )}
        <span className="rate-now" style={{ left: `${at(spot)}%` }} />
        {be !== null && (
          <span className="rate-be" style={{ left: `${at(be)}%` }} />
        )}
      </div>
      <p className="rate-legend">
        <span className={adverseIsLow ? "adverse" : ""}>
          {won(lower)}
          {adverse !== null && adverseIsLow && <em>불리</em>}
        </span>
        <b>현재 {won(spot)}</b>
        <span className={adverse !== null && !adverseIsLow ? "adverse" : ""}>
          {adverse !== null && !adverseIsLow && <em>불리</em>}
          {won(upper)}
        </span>
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
