import { useEffect, useState } from "react";

/** What the agent still needs, docked above the composer.
 *
 *  These controls used to sit inside the message that asked for them. That put
 *  them wherever the conversation happened to be: three turns later the field
 *  was scrolled out of sight while the agent was still waiting on it. Here the
 *  request stays in one place next to where the user is already typing, and it
 *  is visible for exactly as long as it is open.
 *
 *  The thread keeps the *question* — why the value is needed is part of the
 *  conversation. This bar keeps the *control*.
 */

const SLOT_LABEL = {
  amount: "금액 (USD)",
  expected_payment_date: "결제 예정일",
  direction: "수출인가요, 수입인가요",
};

export default function AskBar({ pending, requiredInputs, onSlot, onPlace }) {
  if (pending?.status === "needs_placement") {
    return (
      <Bar label="어느 거래인가요">
        <div className="ask-choices">
          {pending.options.map((option) => (
            <button
              key={option.placement}
              type="button"
              className="choice"
              onClick={() => onPlace(pending.utterance, option.placement)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </Bar>
    );
  }

  const slot = pending?.status === "needs_input" ? pending.missing?.[0] : null;
  if (slot) {
    return (
      <Bar label={SLOT_LABEL[slot] ?? slot}>
        <SlotField slot={slot} onSlot={onSlot} />
      </Bar>
    );
  }

  if (requiredInputs?.length > 0) {
    return (
      <Bar label="손익 기준">
        <ProfitFields onSlot={onSlot} />
      </Bar>
    );
  }

  return null;
}

function Bar({ label, children }) {
  return (
    <div className="askbar" role="group" aria-label={label}>
      <span className="ask-label">{label}</span>
      {children}
    </div>
  );
}

/** Focus moves here when the bar opens: the agent asked, so this is where the
 *  answer goes. The composer is still there for anything else. */
function useAutoFocus() {
  const [node, setNode] = useState(null);
  useEffect(() => {
    node?.focus();
  }, [node]);
  return setNode;
}

function SlotField({ slot, onSlot }) {
  const [value, setValue] = useState("");
  const focus = useAutoFocus();
  const submit = () => value && onSlot({ case: { [slot]: value } });

  return (
    <>
      {slot === "direction" ? (
        <select
          ref={focus}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label={SLOT_LABEL[slot]}
        >
          <option value="">선택하세요</option>
          <option value="수출">수출 (대금을 받음)</option>
          <option value="수입">수입 (대금을 지급)</option>
        </select>
      ) : (
        <input
          ref={focus}
          type={slot === "expected_payment_date" ? "date" : "text"}
          inputMode={slot === "amount" ? "decimal" : undefined}
          value={value}
          placeholder={slot === "amount" ? "100,000" : undefined}
          aria-label={SLOT_LABEL[slot] ?? slot}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
      )}
      <button type="button" onClick={submit}>
        확인
      </button>
    </>
  );
}

function ProfitFields({ onSlot }) {
  const [baseline, setBaseline] = useState("");
  const [floor, setFloor] = useState("");
  const focus = useAutoFocus();
  const submit = () =>
    baseline &&
    floor &&
    onSlot({ profile: { baseline_profit: baseline, profit_floor: floor } });

  return (
    <>
      <input
        ref={focus}
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
      <button type="button" onClick={submit}>
        계산
      </button>
    </>
  );
}
