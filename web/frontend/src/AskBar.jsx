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
  missingInputs,
  decisiveQuestions,
  quoteInputs,
  onSlot,
  onPlace,
  onSplit,
  onUnknown,
}) {
  if (pending?.status === "needs_trade_split") {
    return (
      <Ask key="trade-split" label={pending.question}>
        <ChoiceList
          options={[
            {
              value: "confirm",
              label: `${pending.candidates.length}건의 거래로 나누어 계산`,
            },
          ]}
          onPick={() => onSplit(pending.candidates)}
        />
      </Ask>
    );
  }

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

  const decisive = decisiveQuestions?.[0];
  if (decisive) {
    return (
      <MissingFactField
        key={decisive.question_id}
        item={decisive}
        onSlot={onSlot}
        onUnknown={onUnknown}
      />
    );
  }

  const missing = missingInputs?.find((item) =>
    ["profile", "compliance_declaration", "case"].includes(item.scope),
  );
  if (missing) {
    return (
      <MissingFactField
        key={`${missing.subject_id ?? "program"}:${missing.field}`}
        item={missing}
        onSlot={onSlot}
        onUnknown={onUnknown}
      />
    );
  }

  if (requiredInputs?.length > 0) {
    return (
      <Ask key="profit" label="기준 영업이익과 지키려는 손익 하한을 알려주세요">
        <ProfitFields onSlot={onSlot} />
      </Ask>
    );
  }

  if (quoteInputs?.length > 0) {
    return (
      <Ask key="quote" label="거래 은행이 제시한 선물환 조건을 알려주세요">
        <QuoteFields onSlot={onSlot} />
      </Ask>
    );
  }

  return null;
}

const FACT_LABEL = {
  "company.size": "기업 규모를 알려주세요",
  "company.credit_issue_free": "현재 신용 제한 사유가 없나요?",
  "company.ksure_exporter_grade": "K-SURE 수출자 등급을 알려주세요",
  "company.is_domestic": "대한민국에 소재한 기업인가요?",
  "payment.is_netting": "이 거래는 상계 방식인가요?",
  "payment.is_third_party": "계약 상대방이 아닌 제3자에게 지급하거나 받나요?",
  "payment.uses_mutual_account": "상호계산계정을 사용하나요?",
  "payment.uses_foreign_exchange_bank": "외국환은행을 통해 지급하나요?",
  "trade.payment_term_days": "선적 또는 일람 후 결제일까지 며칠인가요?",
  "financing.purpose": "검토 중인 금융 목적은 무엇인가요?",
  "financing.has_bank_consultation": "취급 금융기관과 보증부 대출 가능성을 상담했나요?",
};

const FACT_OPTIONS = {
  "company.size": [
    { value: "small", label: "중소기업" },
    { value: "mid_sized", label: "중견기업" },
    { value: "large", label: "대기업" },
  ],
  "company.ksure_exporter_grade": ["A", "B", "C", "D", "E", "F", "G", "R", "UNKNOWN"]
    .map((value) => ({ value, label: value })),
  "financing.purpose": [
    { value: "trade_finance", label: "무역금융" },
    { value: "recognized_export_finance", label: "인정 수출금융" },
    { value: "trade_bill_acceptance", label: "무역어음 인수" },
    { value: "export_material_import_lc", label: "수출용 원자재 수입신용장" },
    { value: "recognized_export_promotion_fund", label: "인정 수출진흥자금" },
    { value: "other", label: "기타" },
  ],
};

const DECLARATION_KEY = {
  "payment.is_netting": "is_netting",
  "payment.is_third_party": "is_third_party",
  "payment.uses_mutual_account": "uses_mutual_account",
  "payment.uses_foreign_exchange_bank": "uses_foreign_exchange_bank",
};

function MissingFactField({ item, onSlot, onUnknown }) {
  const question = item.question ?? FACT_LABEL[item.field] ?? `${item.field} 값을 알려주세요`;
  const options = FACT_OPTIONS[item.field];
  const boolean =
    item.field === "company.credit_issue_free" ||
    item.field === "company.is_domestic" ||
    item.field === "financing.has_bank_consultation" ||
    item.scope === "compliance_declaration";

  function answer(value, spoken) {
    if (item.scope === "liquidity" || item.scope === "hedge") {
      onSlot({ profile: { [item.field]: value } }, spoken);
      return;
    }
    if (item.scope === "profile") {
      onSlot({ profile: { company_facts: { [item.field]: value } } }, spoken);
      return;
    }
    if (item.scope === "compliance_declaration") {
      onSlot(
        {
          declaration: {
            case_index: caseIndex(item.subject_id),
            [DECLARATION_KEY[item.field]]: value,
          },
        },
        spoken,
      );
      return;
    }
    onSlot(
      {
        caseIndex: caseIndex(item.subject_id),
        case: { case_facts: { [item.field]: value } },
      },
      spoken,
    );
  }

  if (options) {
    return (
      <Ask label={question}>
        <ChoiceList options={options} onPick={(value, spoken) => answer(value, spoken)} />
        <UnknownButton field={item.field} onUnknown={onUnknown} />
      </Ask>
    );
  }
  if (boolean) {
    return (
      <Ask label={question}>
        <ChoiceList
          options={[
            { value: true, label: "예" },
            { value: false, label: "아니요" },
          ]}
          onPick={(value, spoken) => answer(value, spoken)}
        />
        <UnknownButton field={item.field} onUnknown={onUnknown} />
      </Ask>
    );
  }
  return (
    <Ask label={question}>
      <FactTextField item={item} onAnswer={answer} onUnknown={onUnknown} />
    </Ask>
  );
}

function UnknownButton({ field, onUnknown }) {
  return (
    <button
      className="unknown-choice"
      type="button"
      onClick={() => onUnknown(field)}
    >
      모름 · 추정하지 않음
    </button>
  );
}

function FactTextField({ item, onAnswer, onUnknown }) {
  const [value, setValue] = useState("");
  const focus = useAutoFocus();
  const submit = () => value && onAnswer(value, value);
  return (
    <div className="ask-row">
      <input
        ref={focus}
        inputMode={item.field.endsWith("_days") ? "numeric" : "text"}
        value={value}
        aria-label={FACT_LABEL[item.field] ?? item.field}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => event.key === "Enter" && submit()}
      />
      <button type="button" onClick={submit} disabled={!value}>확인</button>
      <UnknownButton field={item.field} onUnknown={onUnknown} />
    </div>
  );
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
        value={rate}
        placeholder="계약환율"
        aria-label="계약환율"
        onChange={(e) => setRate(e.target.value)}
      />
      <input
        inputMode="decimal"
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

function caseIndex(subjectId) {
  const match = /-(\d+)$/.exec(subjectId ?? "");
  return match ? Math.max(0, Number(match[1]) - 1) : 0;
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
function Ask({ label, children }) {
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
      <button type="button" onClick={submit} disabled={!baseline || !floor}>
        계산
      </button>
    </div>
  );
}
