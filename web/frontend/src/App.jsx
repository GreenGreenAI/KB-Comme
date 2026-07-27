import { useEffect, useRef, useState } from "react";
import Nav from "./Nav.jsx";
import Entry from "./Entry.jsx";
import Thread from "./Thread.jsx";
import Panel from "./Panel.jsx";
import { analyze } from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);

/** The conversation lives in the client. The server is stateless, so whatever
 *  the user has told us is resent each turn — the client already has to render
 *  it all, which makes it the natural owner. */
export default function App() {
  const [view, setView] = useState("entry");
  const [turns, setTurns] = useState([]);
  const [facts, setFacts] = useState({ cases: [{}], profile: {} });
  const [result, setResult] = useState(null);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const threadEnd = useRef(null);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  function say(turn) {
    setTurns((prev) => [...prev, turn]);
  }

  /** One exchange: send everything known, render what came back.
   *
   *  `placement` is only set when the user has answered the "새 거래인가,
   *  수정인가" question. Sending it unasked would reintroduce the guess the
   *  server refuses to make. */
  async function send(utterance, patch = {}, placement = null) {
    // A slot answer always completes the trade currently being described,
    // which is the last one.
    const nextCases = patch.case
      ? [...facts.cases.slice(0, -1), { ...facts.cases.at(-1), ...patch.case }]
      : facts.cases;
    const nextProfile = { ...facts.profile, ...(patch.profile ?? {}) };
    setFacts({ cases: nextCases, profile: nextProfile });

    // When `placement` is set the sentence is being resent after the user
    // answered where it belongs, and it is already in the thread.
    if (utterance && !placement) say({ who: "user", text: utterance });
    setView("work");
    setBusy(true);

    try {
      const data = await analyze({
        cases: nextCases,
        utterance,
        ...nextProfile,
        as_of: today(),
        ...(placement ? { placement } : {}),
      });

      if (data.status === "needs_placement") {
        // Nothing is recorded yet — the sentence has no home until the user
        // says which trade it belongs to.
        setPending(data);
        say({ who: "agent", kind: "placement", ask: data });
        return;
      }

      // Anything the sentence stated is now a known fact, not a question.
      if (data.understood && Object.keys(data.understood).length > 0) {
        setFacts((prev) => ({
          ...prev,
          cases: [
            ...prev.cases.slice(0, -1),
            { ...data.understood, ...stripEmpty(prev.cases.at(-1)) },
          ],
        }));
      }

      if (data.status === "ready") {
        // The server is the authority on how many trades there are now; it
        // just decided whether the sentence added one.
        setFacts((prev) => ({ ...prev, cases: data.result.trade_timeline }));
        setResult(data.result);
        setPending(null);
        say({
          who: "agent",
          kind: "result",
          result: data.result,
          heard: data.understood ?? {},
          spoken: Boolean(utterance),
        });
      } else {
        setPending(data);
        say({ who: "agent", kind: "ask", ask: data });
      }
    } catch (error) {
      say({ who: "agent", kind: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Nav ready={Boolean(result)} />
      <div className="stage" data-view={view}>
        <div className={`view entry ${view === "work" ? "away" : ""}`}>
          <Entry onSend={(text) => send(text)} busy={busy} />
        </div>

        <div className={`view work ${view === "entry" ? "away" : ""}`}>
          <div className="work-wrap">
            <section className="col">
              <Thread
                turns={turns}
                busy={busy}
                pending={pending}
                onSlot={(patch) => send(null, patch)}
                onPlace={(utterance, placement) =>
                  send(utterance, {}, placement)
                }
                endRef={threadEnd}
              />
              <Composer onSend={(text) => send(text)} busy={busy} />
            </section>
            <Panel result={result} pending={pending} facts={facts} />
          </div>
        </div>
      </div>
      <footer>
        TradeFlow MVP · 의사결정 지원 도구이며 투자 권유가 아닙니다 · 최종 판단과
        책임은 이용자에게 있습니다
      </footer>
    </>
  );
}

function stripEmpty(object) {
  return Object.fromEntries(
    Object.entries(object ?? {}).filter(([, value]) => value !== undefined && value !== ""),
  );
}

function Composer({ onSend, busy }) {
  const [text, setText] = useState("");

  function submit() {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setText("");
    onSend(trimmed);
  }

  return (
    <div className="composer">
      <div className="composer-box">
        <textarea
          rows="1"
          value={text}
          placeholder="예: 8월 25일에 수입대금 6만 달러도 나가요"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          className="send"
          type="button"
          onClick={submit}
          disabled={busy}
          aria-label="보내기"
        >
          ↑
        </button>
      </div>
      <p className="composer-hint">
        숫자 계산과 규정 판정은 결정론적 코드가 수행합니다.
      </p>
    </div>
  );
}
