import { useState } from "react";

//: The first one doubles as the placeholder's example and as what Tab fills
//: in, so the sentence a reader is shown is the sentence they get.
//:
//: One per thing the product judges, not four of the same thing. All four used
//: to be a trade and an amount, which taught the scope in a glance — and the
//: lesson was wrong: the engine decides support eligibility and filing duty
//: too, and nobody was ever invited to ask about them. §4.2[2] reads intent
//: from the sentence, so a chip that names a subject really does reorder the
//: answer; these were checked against `read_intent` rather than guessed.
const STARTERS = [
  "10월 24일에 수출대금 10만 달러 받기로 했어요",
  "10월 24일 수출 10만 달러인데 받을 수 있는 지원제도가 있나요",
  "8월 25일 수입 6만 달러를 상계로 처리하는데 신고 대상인가요",
  "12월 3일 수출 15만 달러, 환율이 더 떨어지면 얼마나 손해인가요",
];

export default function Entry({ onSend, busy }) {
  const [text, setText] = useState("");

  function submit(value) {
    const trimmed = (value ?? text).trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
  }

  return (
    <div className="entry-wrap">
      {/* The opening lines arrive in the order they are read. Each carries its
          own delay rather than a shared one, so the sequence is legible in the
          markup instead of hidden in a stylesheet.

          The reveal stops at the standfirst. Below it is the input, and a
          control that fades in is a control the hand has to wait for. */}
      <h1 className="hero">
        <span className="reveal" style={{ animationDelay: "60ms" }}>
          짐작하지 말고
        </span>
        <b className="reveal" style={{ animationDelay: "220ms" }}>
          계산하세요
        </b>
      </h1>
      <p className="standfirst reveal" style={{ animationDelay: "430ms" }}>
        수출입 거래의 환노출을 한국은행 환율로 계산하고, 지원제도 자격과
        신고의무를 규칙으로 판정합니다. 출처와 기준일을 함께 보여드리고,
        환율을 예측하지는 않습니다.
      </p>
      <p className="scope-badge">현재 자동 계산 범위 · USD · T/T 송금</p>

      <div className="prompt">
        <textarea
          rows="2"
          value={text}
          placeholder={`거래를 편하게 설명해 주세요. 예: ${STARTERS[0]}`}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Tab takes the example the placeholder is already showing. Only
            // while the field is empty — once there is text, Tab has to keep
            // moving focus or the form becomes a trap for keyboard users.
            if (e.key === "Tab" && !e.shiftKey && text.trim() === "") {
              e.preventDefault();
              setText(STARTERS[0]);
              return;
            }
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="prompt-foot">
          <p className="prompt-hint">
            {text.trim() === "" ? (
              <>
                <kbd>Tab</kbd> 예시 넣기
              </>
            ) : (
              <>
                <kbd>Enter</kbd> 분석 시작
              </>
            )}
          </p>
          <button
            className="send"
            type="button"
            onClick={() => submit()}
            disabled={busy}
            aria-label="분석 시작"
          >
            ↑
          </button>
        </div>
      </div>

      <div className="chips">
        {STARTERS.map((starter) => (
          <button
            key={starter}
            className="chip"
            type="button"
            onClick={() => submit(starter)}
          >
            {starter}
          </button>
        ))}
      </div>

      <p className="assurance">
        금액 계산과 규정 판정은 모두 결정론적 코드가 수행합니다. AI는 묻고 설명할
        뿐, 수치를 만들지 않습니다.
      </p>
    </div>
  );
}
