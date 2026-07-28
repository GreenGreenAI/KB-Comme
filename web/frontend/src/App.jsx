import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Nav from "./Nav.jsx";
import Entry from "./Entry.jsx";
import Thread from "./Thread.jsx";
import AskBar from "./AskBar.jsx";
import { analyze, health } from "./api.js";

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
  const threadRef = useRef(null);
  const [asOf, setAsOf] = useState(null);

  useEffect(() => {
    let alive = true;
    health()
      .then((info) => {
        const versions = info.fx_snapshots ?? [];
        if (alive && versions.length) setAsOf(versions[versions.length - 1]);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const stick = useRef(true);

  // Remember, before the new turn paints, whether the reader was at the
  // bottom. Someone scrolled up reading an earlier answer should not be
  // yanked to the newest one.
  function rememberPosition() {
    const el = threadRef.current;
    if (!el) return;
    stick.current = el.scrollHeight - el.clientHeight - el.scrollTop < 120;
  }

  useLayoutEffect(() => {
    const el = threadRef.current;
    if (!el || !stick.current) return;
    // Set scrollTop directly rather than scrollIntoView({behavior:"smooth"}):
    // smooth scrolling does not run in a background tab, which left the thread
    // pinned near the top with the newest answer out of sight.
    el.scrollTop = el.scrollHeight;
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
    rememberPosition();
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
      <Nav />
      <div className="stage" data-view={view}>
        <div className={`view entry ${view === "work" ? "away" : ""}`}>
          <Entry onSend={(text) => send(text)} busy={busy} />
        </div>

        {/* The chat is the product surface. It is sized to the viewport and
            scrolls inside itself, so the page never grows a second scrollbar
            as the conversation lengthens. */}
        <div className={`view work ${view === "entry" ? "away" : ""}`}>
          <section className="chat">
            <Thread turns={turns} busy={busy} threadRef={threadRef} />
            {/* Directly above the input, and its own panel. A choice list is
                several lines tall; inside the text box it read as the box
                having swallowed something. */}
            <div className="dock">
              {!busy && (
                <AskBar
                  pending={pending}
                  requiredInputs={
                    result?.hedge_analysis
                      ? []
                      : result?.required_inputs?.hedge ?? []
                  }
                  onSlot={(patch) => send(null, patch)}
                  onPlace={(utterance, placement) =>
                    send(utterance, {}, placement)
                  }
                />
              )}
              <Composer onSend={(text) => send(text)} busy={busy} asOf={asOf} />
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

function stripEmpty(object) {
  return Object.fromEntries(
    Object.entries(object ?? {}).filter(([, value]) => value !== undefined && value !== ""),
  );
}

function Composer({ onSend, busy, asOf }) {
  const [text, setText] = useState("");
  const field = useRef(null);

  // Grow with the text up to a ceiling, then scroll inside. A fixed one-line
  // box hides what the user already typed; an unbounded one pushes the
  // conversation off screen.
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [text]);

  const ready = text.trim().length > 0 && !busy;

  function submit() {
    if (!ready) return;
    setText("");
    onSend(text.trim());
  }

  return (
    <div className="composer">
      <div className="composer-box">
        <textarea
          ref={field}
          rows="1"
          value={text}
          placeholder="거래를 설명하거나 물어보세요"
          aria-label="메시지"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {/* What this session is computing against, and how to send. Both are
            things the user would otherwise have to remember. */}
        <div className="composer-foot">
          <span className="ctx">
            <b>USD</b>
            {asOf ? ` · ECOS ${asOf}` : ""}
          </span>
          {/* Words, not glyphs. ⏎ and ⇧ are missing from enough system fonts
              to render as tofu, and a hint nobody can read is worse than one
              that takes two more characters. */}
          <span className="keys">
            <kbd>Enter</kbd> 전송
            <kbd>Shift + Enter</kbd> 줄바꿈
          </span>
          <button
            className="send"
            type="button"
            onClick={submit}
            disabled={!ready}
            aria-label="보내기"
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
