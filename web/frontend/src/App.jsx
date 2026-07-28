import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Nav from "./Nav.jsx";
import Entry from "./Entry.jsx";
import Thread from "./Thread.jsx";
import AskBar from "./AskBar.jsx";
import { analyze } from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);

/** How long each reasoning step is shown.
 *
 *  The deterministic analysis returns in about 45ms; synthesis over a language
 *  model will not. This paces the mockup the way the finished product will
 *  behave, so the screen is designed against the timing it will actually have
 *  rather than against a timing that disappears the moment the API lands.
 *
 *  Only the pacing is simulated. The steps themselves are read from the
 *  execution plan the server really produced, so nothing is shown as running
 *  that did not run. When streaming replaces this, the step list stays and the
 *  timer goes. */
const STEP_MS = 1000;

/** Fallback for the request bar, in case the turn never reports its arrival.
 *
 *  The turn itself says when it has finished landing — its length depends on
 *  the sentence and on how many blocks the plan produced, so only it can know.
 *  This is the ceiling that keeps the bar from being stranded if that signal
 *  is missed. */
const WRITE_CEILING_MS = 4000;


/** How close the newest question sits to the top of the view. */
const HEAD_GAP = 8;

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The steps an intake turn actually took.
 *
 *  Deciding what to ask is reasoning too — the sentence has to be read, and
 *  what it says has to be weighed against the trades already known. Naming
 *  those makes a question arrive the same way an answer does, and each name
 *  is an operation the server really performed.
 */
function stepsForAsk(data, utterance) {
  const steps = [];
  if (utterance) steps.push("read");
  if (data.status === "needs_placement") steps.push("placement");
  else steps.push("slots");
  return steps;
}

/** Walk a step list, holding each one on screen for its turn. */
async function walk(steps, show) {
  for (let index = 0; index < steps.length; index += 1) {
    show({ steps, index });
    await wait(STEP_MS);
  }
  show(null);
}

/** The steps this answer actually took, in the order §4.1 runs them. */
function stepsFor(result) {
  const ran = result?.workers?.completed ?? [];
  const order = ["exposure", "source_verification", "market_scenario", "support", "compliance", "hedge"];
  const steps = order.filter((name) => ran.includes(name));
  return [...steps, "synthesis"];
}

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
  const [thinking, setThinking] = useState(null);
  const [writing, setWriting] = useState(false);
  const threadRef = useRef(null);
  const stick = useRef(true);

  /** Leave room under the conversation so the newest exchange can reach the
   *  top of the view.
   *
   *  Without it a short exchange simply cannot be scrolled up — there is
   *  nothing below it to scroll into — so it stays pinned to the bottom edge
   *  and the answer is written downward out of sight. The spacer holds exactly
   *  what is left over, so it disappears the moment an exchange is tall enough
   *  to fill the thread on its own and never leaves a gap behind. */
  function fitTail(el) {
    const spacer = el.querySelector(".tail");
    if (!spacer) return;
    const heads = el.querySelectorAll(".turn.user");
    const head = heads[heads.length - 1];
    const last = spacer.previousElementSibling;
    if (!head || !last) {
      spacer.style.height = "0px";
      return;
    }
    // Measured from the neighbour rather than from the spacer itself: reading
    // the spacer's own box would mean zeroing it first, and a forced reflow
    // every frame of the cascade.
    const used = last.getBoundingClientRect().bottom - head.getBoundingClientRect().top;
    spacer.style.height = `${Math.max(0, Math.round(el.clientHeight - used - HEAD_GAP))}px`;
  }

  /** Where the bottom of the real conversation sits, in scroll coordinates.
   *  Not scrollHeight — that includes the spacer, and easing into empty space
   *  would carry the answer off the top of the view for no reason. */
  function contentFoot(el) {
    const spacer = el.querySelector(".tail");
    if (!spacer) return el.scrollHeight;
    return spacer.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
  }

  const exchange = turns.filter((turn) => turn.who === "user").length;

  /** The newest question goes to the top of the view when it is asked.
   *
   *  The answer is then written downward into empty space. Pinning to the
   *  bottom instead started every answer at the bottom edge of the thread, so
   *  the reader watched its first line leave while the rest arrived. */
  useLayoutEffect(() => {
    const el = threadRef.current;
    if (!el || !stick.current) return;
    fitTail(el);
    const max = el.scrollHeight - el.clientHeight;
    const heads = el.querySelectorAll(".turn.user");
    const head = heads[heads.length - 1];
    if (!head) {
      el.scrollTop = max;
      return;
    }
    const top =
      head.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
    el.scrollTop = Math.max(0, Math.min(top - HEAD_GAP, max));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exchange]);

  /** Follow the exchange down as it arrives.
   *
   *  The anchor above happens once, when the question is asked — at which point
   *  there is no answer yet. Everything that gives it height arrives over the
   *  next few seconds, and without this the answer grows past the bottom of the
   *  thread while the reader watches the top of it.
   *
   *  It eases rather than pins, so the view moves at the pace the answer is
   *  being written, and it stops at the foot of the conversation rather than at
   *  the foot of the spacer.
   *
   *  What makes it yield is a real input — a wheel, a drag, a key. The previous
   *  version watched scrollTop for a value it had not set, which cannot tell a
   *  reader apart from a layout change; the request panel appearing and the
   *  thinking line being replaced both move the scroll on their own, and the
   *  follower read that as the reader taking over and let go. It then stayed
   *  let go, so the next answer was written entirely off screen. */
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return undefined;

    const release = () => {
      stick.current = false;
    };
    el.addEventListener("wheel", release, { passive: true });
    el.addEventListener("touchmove", release, { passive: true });
    el.addEventListener("keydown", release);

    const follow = setInterval(() => {
      fitTail(el);
      if (!stick.current) {
        clearInterval(follow);
        return;
      }
      const target = Math.min(
        contentFoot(el) - el.clientHeight,
        el.scrollHeight - el.clientHeight,
      );
      const delta = target - el.scrollTop;
      if (delta <= 0.5) {
        if (!busy && !writing) clearInterval(follow);
        return;
      }
      el.scrollTop += Math.max(delta * 0.16, 0.5);
    }, 16);

    return () => {
      clearInterval(follow);
      el.removeEventListener("wheel", release);
      el.removeEventListener("touchmove", release);
      el.removeEventListener("keydown", release);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, writing, turns.length]);

  function say(turn) {
    setTurns((prev) => [...prev, turn]);
  }

  /** One exchange: send everything known, render what came back.
   *
   *  `placement` is only set when the user has answered the "새 거래인가,
   *  수정인가" question. Sending it unasked would reintroduce the guess the
   *  server refuses to make. */
  async function send(utterance, patch = {}, placement = null, said = null) {
    // A slot answer always completes the trade currently being described,
    // which is the last one.
    const nextCases = patch.case
      ? [...facts.cases.slice(0, -1), { ...facts.cases.at(-1), ...patch.case }]
      : facts.cases;
    const nextProfile = { ...facts.profile, ...(patch.profile ?? {}) };
    setFacts({ cases: nextCases, profile: nextProfile });

    // What the user said, as the thread should carry it. A typed sentence is
    // its own text. An answer given through the request panel says what was
    // chosen or entered — the panel is gone a moment later, and without this
    // the conversation read as the agent asking a question and then answering
    // itself. When `placement` is set the original sentence is already in the
    // thread; what is new is the answer about where it belongs.
    const spoken = said ?? (placement ? null : utterance);

    // Someone who just asked a question wants to see the answer, so following
    // resumes with every send. Only the reader scrolling during the arrival
    // turns it off again.
    stick.current = true;
    if (spoken) say({ who: "user", text: spoken });
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
        await walk(stepsForAsk(data, utterance), setThinking);
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
        // Walk the plan's steps before showing the answer. The result is
        // already in hand — this paces the reveal, it does not wait on work.
        await walk(stepsFor(data.result), setThinking);

        // The server is the authority on how many trades there are now; it
        // just decided whether the sentence added one.
        setFacts((prev) => ({ ...prev, cases: data.result.trade_timeline }));
        setResult(data.result);
        setPending(null);
        setWriting(true);
        setTimeout(() => setWriting(false), WRITE_CEILING_MS);
        say({
          who: "agent",
          kind: "result",
          result: data.result,
          heard: data.understood ?? {},
          spoken: Boolean(utterance),
        });
      } else {
        await walk(stepsForAsk(data, utterance), setThinking);
        setPending(data);
        say({ who: "agent", kind: "ask", ask: data });
      }
    } catch (error) {
      say({ who: "agent", kind: "error", text: error.message });
    } finally {
      setThinking(null);
      setBusy(false);
    }
  }

  return (
    <>
      {/* Home returns to the opening screen without discarding anything. The
          conversation is still there, and typing continues it — a brand click
          should not be able to destroy work the user cannot get back. */}
      <Nav onHome={() => setView("entry")} />
      <div className="stage" data-view={view}>
        <div className={`view entry ${view === "work" ? "away" : ""}`}>
          <Entry onSend={(text) => send(text)} busy={busy} />
        </div>

        {/* The chat is the product surface. It is sized to the viewport and
            scrolls inside itself, so the page never grows a second scrollbar
            as the conversation lengthens. */}
        <div className={`view work ${view === "entry" ? "away" : ""}`}>
          <section className="chat">
            <Thread
              turns={turns}
              busy={busy}
              thinking={thinking}
              onArrived={() => setWriting(false)}
              threadRef={threadRef}
            />
            {/* Directly above the input, and its own panel. A choice list is
                several lines tall; inside the text box it read as the box
                having swallowed something.

                It waits for the answer to finish writing itself. Asking for
                the next value while the sentence is still arriving reads as
                the agent interrupting itself. */}
            <div className="dock">
              {!busy && !writing && (
                <AskBar
                  pending={pending}
                  requiredInputs={
                    result?.hedge_analysis
                      ? []
                      : result?.required_inputs?.hedge ?? []
                  }
                  onSlot={(patch, said) => send(null, patch, null, said)}
                  onPlace={(utterance, placement, said) =>
                    send(utterance, {}, placement, said)
                  }
                />
              )}
              <Composer onSend={(text) => send(text)} busy={busy} />
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

function Composer({ onSend, busy }) {
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
        <div className="composer-foot">
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
