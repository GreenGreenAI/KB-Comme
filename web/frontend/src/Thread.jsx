import { useState } from "react";
import { won, pct } from "./api.js";

const SLOT_LABEL = {
  amount: "금액 (USD)",
  expected_payment_date: "결제 예정일",
  direction: "방향",
};

/** The conversation, including the trace of which tools actually ran. That
 *  trace is not decoration: it is how a reader can tell the figures came from
 *  a calculation rather than from the model's prose. */
export default function Thread({ turns, busy, pending, onSlot, endRef }) {
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
            first={!turns.slice(0, index).some((t) => t.kind === "result")}
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

function AgentTurn({ turn, live, onSlot, first }) {
  if (turn.kind === "error") {
    return (
      <div className="turn agent">
        <span className="who">TradeFlow</span>
        <p>{turn.text}</p>
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
  const net = result.cashflow_analysis?.net_exposure?.[0]?.amount;
  const swing =
    market && net
      ? Math.round(
          Number(net) * (Number(market.band_lower) - Number(market.spot_rate)),
        )
      : null;

  return (
    <div className="turn agent">
      <span className="who">TradeFlow</span>

      <div className="trace">
        {result.workers.completed.map((name) => (
          <span className="ok" key={name}>
            {
              {
                exposure: "순노출·자금공백 산출",
                market_scenario: "변동성 추정 — 최근 60영업일",
                hedge: "헤지비율 산출",
              }[name]
            }
          </span>
        ))}
        {Object.entries(result.workers.skipped).map(([name, reason]) => (
          <span className="wait" key={name}>
            {name} — {reason}
          </span>
        ))}
      </div>

      {first && market && swing !== null ? (
        <p>
          계산했습니다.{" "}
          <strong>
            결제일까지 환율이 {won(market.band_lower)}원까지 내려갈 수 있고
          </strong>
          , 그러면 받는 금액이 지금보다{" "}
          <strong>{won(Math.abs(swing))}원 {swing < 0 ? "적어집니다" : "많아집니다"}.</strong>
        </p>
      ) : hedge ? (
        <p>
          손익분기 환율은 <strong>{won(hedge.breakeven_rate)}원</strong>이고, 최소{" "}
          <strong>{pct(hedge.optimal_ratio)}</strong>만 헤지하면 목표 이익을 지킬 수
          있습니다. 오른쪽에서 세 가지를 나란히 비교해 보세요.
        </p>
      ) : (
        <p>다시 계산했습니다. 오른쪽에서 결과를 확인하실 수 있어요.</p>
      )}

      {!hedge && (
        <>
          <p>
            영업이익을 알려주시면 손익분기 환율과 필요한 헤지 비율까지 계산해
            드릴게요.
          </p>
          {live && <ProfitInput onSlot={onSlot} />}
        </>
      )}

      {hedge?.status === "HEDGE_INSUFFICIENT" && (
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
  const [value, setValue] = useState("");
  const submit = () =>
    value &&
    onSlot({
      profile: { baseline_profit: value, profit_floor: String(Math.round(Number(value.replace(/,/g, "")) * 0.67)) },
    });

  return (
    <>
      <div className="slotline">
        <input
          inputMode="decimal"
          value={value}
          placeholder="영업이익 (원)"
          aria-label="기준 영업이익"
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <button type="button" onClick={submit}>계산</button>
      </div>
      <div className="quick">
        <button type="button" onClick={() => onSlot({ profile: {} })}>
          잘 모르겠어요
        </button>
      </div>
    </>
  );
}
