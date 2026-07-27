import { useState } from "react";
import { won, pct } from "./api.js";

const WORKER_LABEL = {
  exposure: "순노출·자금공백 산출",
  source_verification: "공식 출처 검증 확인",
  market_scenario: "변동성 추정 — 최근 60영업일",
  hedge: "헤지비율 산출",
  support: "지원제도 규칙 판정",
  compliance: "신고의무 규칙 판정",
};

const SLOT_LABEL = {
  amount: "금액 (USD)",
  expected_payment_date: "결제 예정일",
  direction: "방향",
};

/** The conversation, including the trace of which tools actually ran. That
 *  trace is not decoration: it is how a reader can tell the figures came from
 *  a calculation rather than from the model's prose. */
export default function Thread({ turns, busy, pending, onSlot, onPlace, endRef }) {
  return (
    <div className="thread">
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
            onPlace={onPlace}
            first={!turns.slice(0, index).some((t) => t.kind === "result")}
            previous={
              turns
                .slice(0, index)
                .filter((t) => t.kind === "result")
                .at(-1)?.result ?? null
            }
            onSlot={onSlot}
          />
        ),
      )}

      {busy && (
        <div className="turn agent">
          <span className="who">TradeFlow</span>
          <div className="trace">
            <span className="wait">계산 중…</span>
          </div>
        </div>
      )}

      <div ref={endRef} />
    </div>
  );
}

function AgentTurn({ turn, live, onSlot, onPlace, first, previous }) {
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
        {live && (
          <div className="choices">
            {turn.ask.options.map((option) => (
              <button
                className="choice"
                type="button"
                key={option.placement}
                onClick={() => onPlace(turn.ask.utterance, option.placement)}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
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
        {live && <SlotInput missing={turn.ask.missing} onSlot={onSlot} />}
      </div>
    );
  }

  const result = turn.result;
  const market = result.market_scenario;
  const hedge = result.hedge_analysis;
  const swing = market?.adverse_cashflow_amount ?? null;
  const hedgeInputs = result.required_inputs?.hedge ?? [];

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

      {first && market && swing !== null ? (
        <p>
          계산했습니다.{" "}
          <strong>
            결제일까지 불리한 환율이 {won(market.adverse_rate)}원일 수 있고
          </strong>
          , 그러면 받는 금액이 지금보다{" "}
          <strong>
            {won(swing)}원{" "}
            {market.adverse_cashflow_direction === "decrease"
              ? "적어집니다"
              : "많아집니다"}.
          </strong>
        </p>
      ) : hedgeIsNew ? (
        <p>
          손익분기 환율은 <strong>{won(hedge.breakeven_rate)}원</strong>이고, 최소{" "}
          <strong>{pct(hedge.optimal_ratio)}</strong>만 헤지하면 목표 이익을 지킬 수
          있습니다.
        </p>
      ) : tradesChanged ? (
        <p>거래 {tradeCount}건으로 다시 계산했습니다.</p>
      ) : opened.length > 0 ? (
        <p>{opened.map((name) => WORKER_LABEL[name] ?? name).join(" · ")}까지 채웠습니다.</p>
      ) : unread ? (
        <p>
          그 문장에서는 거래 정보를 읽지 못해 계산이 달라지지 않았습니다. 금액 ·
          결제일 · 수출입 여부는 문장으로 알려주실 수 있습니다.
        </p>
      ) : (
        <p>다시 계산했습니다.</p>
      )}

      {/* Asked once. Repeating the request every turn read as if the answer
          had not been received. */}
      {!hedge && hedgeInputs.length > 0 && live && (
        <>
          <p>
            기준 영업이익과 회사가 지키려는 목표 손익 하한을 각각 입력해 주세요.
            입력하지 않은 하한을 임의로 만들지 않습니다.
          </p>
          <ProfitInput onSlot={onSlot} />
        </>
      )}

      {first && !hedge && hedgeInputs.length === 0 && result.workers.skipped.hedge && (
        <p>{result.workers.skipped.hedge}</p>
      )}

      {hedgeIsNew && hedge?.status === "HEDGE_INSUFFICIENT" && (
        <p>
          전액을 헤지해도 목표 이익을 지킬 수 없습니다. 헤지 비율을 임의로
          제시하지 않고 다른 방법을 함께 검토해야 합니다.
        </p>
      )}
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

/** Asking in prose but accepting a typed value: the wording stays
 *  conversational while the value stays unambiguous. */
function SlotInput({ missing, onSlot }) {
  const slot = missing?.[0];
  const [value, setValue] = useState("");
  if (!slot) return null;

  const submit = () => value && onSlot({ case: { [slot]: value } });

  return (
    <div className="slotline">
      {slot === "direction" ? (
        <select value={value} onChange={(e) => setValue(e.target.value)} aria-label={SLOT_LABEL[slot]}>
          <option value="">선택하세요</option>
          <option value="수출">수출 (대금을 받음)</option>
          <option value="수입">수입 (대금을 지급)</option>
        </select>
      ) : (
        <input
          type={slot === "expected_payment_date" ? "date" : "text"}
          inputMode={slot === "amount" ? "decimal" : undefined}
          value={value}
          placeholder={slot === "amount" ? "100,000" : undefined}
          aria-label={SLOT_LABEL[slot] ?? slot}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
      )}
      <button type="button" onClick={submit}>확인</button>
    </div>
  );
}

function ProfitInput({ onSlot }) {
  const [baseline, setBaseline] = useState("");
  const [floor, setFloor] = useState("");
  const submit = () =>
    baseline &&
    floor &&
    onSlot({
      profile: { baseline_profit: baseline, profit_floor: floor },
    });

  return (
    <div className="slotline">
      <input
        inputMode="decimal"
        value={baseline}
        placeholder="기준 영업이익 (원)"
        aria-label="기준 영업이익"
        onChange={(e) => setBaseline(e.target.value)}
      />
      <input
        inputMode="decimal"
        value={floor}
        placeholder="목표 손익 하한 (원)"
        aria-label="목표 손익 하한"
        onChange={(e) => setFloor(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <button type="button" onClick={submit}>계산</button>
    </div>
  );
}
