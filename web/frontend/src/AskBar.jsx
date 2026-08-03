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

/** A hair over the .ask-in animation in styles.css. */
const ASK_IN_MS = 420;

const FALLBACK_QUESTION = {
  amount: "거래 금액이 얼마인가요?",
  expected_payment_date: "대금을 주고받기로 한 날짜가 언제인가요?",
  direction: "수출 건인가요, 수입 건인가요?",
};

const DIRECTION_OPTIONS = [
  { value: "수출", label: "수출", hint: "대금을 받습니다" },
  { value: "수입", label: "수입", hint: "대금을 지급합니다" },
];

export default function AskBar({
  pending,
  requiredInputs,
  quoteInputs,
  profileInputs,
  factInputs,
  //: 지금 열려 있는 요청이 무엇을 여는지. 서버가 워커를 건너뛰며 남긴 이유를
  //: 그대로 받습니다 — 화면이 다시 쓰면 두 문장이 갈라집니다.
  askNote,
  onSlot,
  onPlace,
}) {
  if (pending?.status === "needs_placement") {
    return (
      <Ask key="placement" label="어느 거래인가요">
        <ChoiceList
          options={pending.options.map((option) => ({
            value: option.placement,
            label: option.label,
          }))}
          onPick={(value, label) => onPlace(pending.utterance, value, label)}
        />
      </Ask>
    );
  }

  // Field and wording come paired from intake. Reading the field from one
  // list and the question from another put a direction chooser under a
  // question about the date.
  const asked =
    pending?.status === "needs_input"
      ? pending.asked?.[0] ?? (pending.missing?.[0]
          ? { field: pending.missing[0], question: null }
          : null)
      : null;
  const slot = asked?.field ?? null;
  const question = asked?.question ?? FALLBACK_QUESTION[slot] ?? slot;

  if (slot === "direction") {
    return (
      <Ask key={`direction:${question}`} label={question}>
        <ChoiceList
          options={DIRECTION_OPTIONS}
          onPick={(value, label) => onSlot({ case: { direction: value } }, label)}
        />
      </Ask>
    );
  }

  if (slot) {
    return (
      <Ask key={`slot:${slot}`} label={question}>
        <SlotField slot={slot} onSlot={onSlot} />
      </Ask>
    );
  }

  // §5.4's two most-asked company facts. An account states them once and is
  // never asked again — this is the same two by hand, so a company that has
  // not signed up gets a judgement instead of a list of what it would need.
  if (profileInputs?.length > 0) {
    return <ProfileAsk key="profile" note={askNote} onSlot={onSlot} />;
  }

  // The facts a rule that already ran is still short of. Nothing here decides
  // what to ask or how to word it — the server sends the question, the answers
  // on offer, and which product each one opens, all read from the rules and
  // the fact catalog. A list of fields written on this side would be a copy of
  // the rulepack, and it would drift the first time a rule changed.
  if (factInputs?.length > 0) {
    return (
      <FactAsk
        key={`fact:${factInputs[0].field}`}
        ask={factInputs[0]}
        onSlot={onSlot}
      />
    );
  }

  if (requiredInputs?.length > 0) {
    return (
      <Ask
        key="profit"
        label="기준 영업이익과 지키려는 손익 하한을 알려주세요"
        note={askNote}
      >
        <ProfitFields onSlot={onSlot} />
      </Ask>
    );
  }

  if (quoteInputs?.length > 0) {
    return (
      <Ask
        key="quote"
        label="거래 은행이 제시한 선물환 조건을 알려주세요"
        note={askNote}
      >
        <QuoteFields onSlot={onSlot} />
      </Ask>
    );
  }

  return null;
}

/** The forward quote, which only the company has.
 *
 *  §5.3 will not produce a hedge ratio from public market data — a forward
 *  rate is what one bank offered to one company, and no snapshot stands in for
 *  that. So the four things a bank tells you are asked for, and everything
 *  about the quote's scope (which trades, which currencies, which side, the
 *  settlement date) is derived server-side from the trades already entered.
 *  Asking for those too would let the two disagree.
 */
function QuoteFields({ onSlot }) {
  const [provider, setProvider] = useState("");
  const [rate, setRate] = useState("");
  const [cost, setCost] = useState("");
  const [until, setUntil] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const focus = useAutoFocus();
  const ready = provider && rate && cost && until && confirmed;

  const submit = () =>
    ready &&
    onSlot(
      {
        quote: {
          provider,
          contract_rate: rate,
          cost_rate: cost,
          valid_until: until,
          confirmed,
        },
      },
      `${provider} 선물환 ${rate}원 · 수수료율 ${cost} · ${until}까지 유효`,
    );

  return (
    <div className="ask-row quote">
      <input
        ref={focus}
        value={provider}
        placeholder="은행"
        aria-label="은행"
        onChange={(e) => setProvider(e.target.value)}
      />
      <input
        inputMode="decimal"
        autoComplete="off"
        value={rate}
        placeholder="계약환율"
        aria-label="계약환율"
        onChange={(e) => setRate(e.target.value)}
      />
      <input
        inputMode="decimal"
        autoComplete="off"
        value={cost}
        placeholder="수수료율 (0.0025)"
        aria-label="수수료율"
        onChange={(e) => setCost(e.target.value)}
      />
      <input
        type="date"
        value={until}
        aria-label="유효기한"
        onChange={(e) => setUntil(e.target.value)}
      />
      {/* An indicative rate and a confirmed one are different facts, and §5.3
          treats them differently. Only the person holding the quote can say
          which this is, so it is asked rather than assumed. */}
      <label className="check">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span className="tickbox" aria-hidden="true" />
        은행이 확인해 준 호가입니다
      </label>
      <button type="button" onClick={submit} disabled={!ready}>
        계산
      </button>
    </div>
  );
}

/** The request panel, and the way it comes in.
 *
 *  It arrives with the same gesture the answer uses — it is the end of the
 *  agent's turn, not a separate piece of chrome that appeared underneath.
 *
 *  The class comes back off once the fade has had its time. An animation that
 *  is applied but never advances holds its opening frame, and here that frame
 *  is an invisible panel with the only controls the user needs in it. Every
 *  call site keys this on the question, so a new question is a new panel and
 *  arrives rather than silently swapping its contents.
 */
function Ask({ label, note, children }) {
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setEntered(true), ASK_IN_MS);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div
      className={entered ? "ask" : "ask ask-in"}
      role="group"
      aria-label={label}
    >
      <p className="ask-label">{label}</p>
      {/* What answering opens. A question with no stated purpose reads as a
          form; the same question with one is an offer the reader can decline. */}
      {note && <p className="ask-note">{note}</p>}
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
      onPick(options[index].value, options[index].label);
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
      onPick(options[active].value, options[active].label);
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
          onClick={() => onPick(option.value, option.label)}
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

  if (slot === "amount") return <AmountField onSlot={onSlot} />;

  const submit = () => value && onSlot({ case: { [slot]: value } }, value);

  return (
    <div className="ask-row">
      <input
        ref={focus}
        type={slot === "expected_payment_date" ? "date" : "text"}
        value={value}
        aria-label={slot}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <button type="button" onClick={submit} disabled={!value}>
        확인
      </button>
    </div>
  );
}

const GROUPED = /\B(?=(\d{3})+(?!\d))/g;

const group = (raw) => raw.replace(/^(\d+)/, (whole) => whole.replace(GROUPED, ","));

/** An amount, shown the way it is read.
 *
 *  Six digits in a row are hard to check at a glance, which matters when the
 *  number decides every figure below it. Separators go in as the user types
 *  and come back out before the value is sent — the API takes a plain number,
 *  and formatting is a reading aid, not data.
 */
function AmountField({ onSlot }) {
  const [raw, setRaw] = useState("");
  const focus = useAutoFocus();
  const submit = () =>
    raw && onSlot({ case: { amount: raw } }, `${group(raw)} USD`);

  function onChange(event) {
    const digits = event.target.value.replace(/[^\d.]/g, "");
    setRaw(digits);
  }

  const shown = raw ? group(raw) : "";
  const spoken = raw ? readable(raw) : null;

  return (
    <div className="ask-row">
      <span className="money">
        <i>$</i>
        <input
          ref={focus}
          inputMode="decimal"
          autoComplete="off"
          value={shown}
          placeholder="100,000"
          aria-label="금액 (USD)"
          onChange={onChange}
          onKeyDown={(e) => e.key === "Enter" && submit()}
        />
        <em>USD</em>
      </span>
      {/* The same number in words. A mistyped zero is invisible in digits and
          obvious here. */}
      {spoken && <span className="money-read">{spoken}</span>}
      <button type="button" onClick={submit} disabled={!raw}>
        확인
      </button>
    </div>
  );
}

function readable(raw) {
  const value = Number(raw);
  if (!Number.isFinite(value) || value === 0) return null;
  if (value >= 100000000) return `${trim(value / 100000000)}억 달러`;
  if (value >= 10000) return `${trim(value / 10000)}만 달러`;
  return null;
}

const trim = (n) => Number(n.toFixed(2)).toLocaleString("ko-KR");

const SIZE_OPTIONS = [
  { value: "small", label: "중소기업" },
  { value: "mid_sized", label: "중견기업" },
  { value: "large", label: "대기업" },
];

const CREDIT_OPTIONS = [
  { value: true, label: "없습니다", hint: "연체·부도·대위변제 등" },
  { value: false, label: "있습니다" },
];

/** The two facts §5.4 names first.
 *
 *  Asked as choices rather than free text: 기업규모 is an enum in the rulepack
 *  and 신용 상태 is a boolean, and a typed answer would have to be guessed back
 *  into one — which is the guess §1.1 refuses. Both are sent together so the
 *  rules see one company rather than two halves of one. */
/** One fact a judgement is waiting for, asked in the rules' own words.
 *
 *  One at a time and in rule order. A form of six fields is a form; a question
 *  with three answers is a conversation, and the next question only exists
 *  because the last answer did not close the judgement.
 *
 *  The label says what it opens. 「K-SURE 등급을 아시나요」 with no reason is a
 *  demand; the same question under 「단기수출보험(선적후·개별)을 판정하려면」 is
 *  an offer, and the reader can decide it is not worth answering.
 */
function FactAsk({ ask, onSlot }) {
  // Some of these are not facts about the company at all — they are the trade
  // detail a fact is computed from, and they travel back the way every other
  // trade detail does. The server says which, because the server is what knows
  // whether it asks for a value or for the input to one.
  const answer = (value, label) =>
    onSlot(
      ask.answer_as === "case"
        ? // `case_id` names the trade the judgement is about. The screen does
          // not work it out — it is the rule's own subject, and guessing it
          // from the order the trades were typed in is how the answer used to
          // land on the wrong one.
          { case: { [ask.field]: value }, caseId: ask.case_id }
        : { facts: { [ask.field]: value } },
      label ?? value,
    );

  if (ask.options?.length > 0) {
    return (
      <Ask label={ask.question} note={ask.opens ? `${ask.opens} 판정에 필요합니다` : null}>
        <ChoiceList
          options={ask.options.map((option) => ({
            value: option.value,
            label: option.label,
          }))}
          onPick={answer}
        />
      </Ask>
    );
  }
  return (
    <Ask label={ask.question} note={ask.opens ? `${ask.opens} 판정에 필요합니다` : null}>
      <FactField kind={ask.kind} onSubmit={answer} />
    </Ask>
  );
}

function FactField({ kind, onSubmit }) {
  const [value, setValue] = useState("");
  const focus = useAutoFocus();
  const submit = () => value.trim() && onSubmit(value.trim());

  return (
    <div className="ask-row">
      <input
        ref={focus}
        type={kind === "date" ? "date" : "text"}
        value={value}
        autoComplete="off"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => event.key === "Enter" && submit()}
      />
      <button type="button" onClick={submit} disabled={!value.trim()}>
        확인
      </button>
    </div>
  );
}

function ProfileAsk({ note, onSlot }) {
  const [size, setSize] = useState(null);

  if (size === null) {
    return (
      <Ask label="기업규모가 어떻게 되나요?" note={note}>
        <ChoiceList options={SIZE_OPTIONS} onPick={(value) => setSize(value)} />
      </Ask>
    );
  }
  // Sent together, not one at a time: the rules read one company, and a size
  // that arrived without its credit standing would be judged on half a profile and
  // then judged again on the other half.
  return (
    <Ask label="연체·부도 등 신용 이슈가 있으신가요?">
      <ChoiceList
        options={CREDIT_OPTIONS}
        onPick={(value, label) =>
          onSlot(
            { profile: { company_size: size, credit_issue_free: value } },
            `${SIZE_OPTIONS.find((o) => o.value === size).label} · 신용 이슈 ${label}`,
          )
        }
      />
    </Ask>
  );
}

function ProfitFields({ onSlot }) {
  const [baseline, setBaseline] = useState("");
  const [floor, setFloor] = useState("");
  const focus = useAutoFocus();
  const submit = () =>
    baseline &&
    floor &&
    onSlot(
      { profile: { baseline_profit: baseline, profit_floor: floor } },
      `기준 영업이익 ${group(baseline)}원 · 목표 손익 하한 ${group(floor)}원`,
    );

  return (
    <div className="ask-row">
      <input
        ref={focus}
        inputMode="decimal"
        autoComplete="off"
        value={baseline}
        placeholder="기준 영업이익 (원)"
        aria-label="기준 영업이익"
        onChange={(e) => setBaseline(e.target.value)}
      />
      <input
        inputMode="decimal"
        autoComplete="off"
        value={floor}
        placeholder="목표 손익 하한 (원)"
        aria-label="목표 손익 하한"
        onChange={(e) => setFloor(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <button type="button" onClick={submit} disabled={!baseline || !floor}>
        계산
      </button>
    </div>
  );
}
