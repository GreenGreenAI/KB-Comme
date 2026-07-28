import { useEffect, useRef, useState } from "react";

/** What the agent still needs, docked in the input box.
 *
 *  These controls used to sit inside the message that asked for them. That put
 *  them wherever the conversation happened to be: three turns later the field
 *  was scrolled out of sight while the agent was still waiting on it. Here the
 *  request stays next to where the user is already typing, and it is visible
 *  for exactly as long as it is open.
 *
 *  The thread keeps the *question* — why the value is needed is part of the
 *  conversation. This keeps the *control*.
 */

const SLOT_LABEL = {
  amount: "금액 (USD)",
  expected_payment_date: "결제 예정일",
  direction: "수출인가요, 수입인가요",
};

const DIRECTION_OPTIONS = [
  { value: "수출", label: "수출", hint: "대금을 받습니다" },
  { value: "수입", label: "수입", hint: "대금을 지급합니다" },
];

export default function AskBar({ pending, requiredInputs, onSlot, onPlace }) {
  if (pending?.status === "needs_placement") {
    return (
      <Ask label="어느 거래인가요">
        <ChoiceList
          options={pending.options.map((option) => ({
            value: option.placement,
            label: option.label,
          }))}
          onPick={(value) => onPlace(pending.utterance, value)}
        />
      </Ask>
    );
  }

  const slot = pending?.status === "needs_input" ? pending.missing?.[0] : null;

  if (slot === "direction") {
    return (
      <Ask label={SLOT_LABEL.direction}>
        <ChoiceList
          options={DIRECTION_OPTIONS}
          onPick={(value) => onSlot({ case: { direction: value } })}
        />
      </Ask>
    );
  }

  if (slot) {
    return (
      <Ask label={SLOT_LABEL[slot] ?? slot} inline>
        <SlotField slot={slot} onSlot={onSlot} />
      </Ask>
    );
  }

  if (requiredInputs?.length > 0) {
    return (
      <Ask label="손익 기준" inline>
        <ProfitFields onSlot={onSlot} />
      </Ask>
    );
  }

  return null;
}

function Ask({ label, inline = false, children }) {
  return (
    <div className={`ask ${inline ? "ask-inline" : ""}`} role="group" aria-label={label}>
      <span className="ask-label">{label}</span>
      {children}
    </div>
  );
}

/** A list you pick from, keyboard first.
 *
 *  Stacked rather than inline because the options are read, not scanned: each
 *  one is a different thing to do, and side-by-side pills invite a click
 *  before the second one has been read. Number keys select directly, arrows
 *  move, Enter confirms — the mouse is never required.
 */
function ChoiceList({ options, onPick }) {
  const [active, setActive] = useState(0);
  const box = useRef(null);

  useEffect(() => {
    box.current?.focus();
  }, []);

  function onKeyDown(event) {
    const index = Number(event.key) - 1;
    if (index >= 0 && index < options.length) {
      event.preventDefault();
      onPick(options[index].value);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : options.length - 1;
      setActive((current) => (current + step) % options.length);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      onPick(options[active].value);
    }
  }

  return (
    <div
      className="choices"
      ref={box}
      tabIndex={0}
      role="listbox"
      aria-activedescendant={`choice-${active}`}
      onKeyDown={onKeyDown}
    >
      {options.map((option, index) => (
        <button
          type="button"
          id={`choice-${index}`}
          key={option.value}
          role="option"
          aria-selected={index === active}
          className={`choice ${index === active ? "on" : ""}`}
          tabIndex={-1}
          onMouseEnter={() => setActive(index)}
          onClick={() => onPick(option.value)}
        >
          <span className="choice-key">{index + 1}</span>
          <span className="choice-label">{option.label}</span>
          {option.hint && <span className="choice-hint">{option.hint}</span>}
        </button>
      ))}
    </div>
  );
}

/** Focus moves here when the request opens: the agent asked, so this is where
 *  the answer goes. The composer is still there for anything else. */
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
