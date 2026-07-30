import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Nav from "./Nav.jsx";
import Entry from "./Entry.jsx";
import Thread from "./Thread.jsx";
import AskBar from "./AskBar.jsx";
import Login from "./Login.jsx";
import Notices from "./Notices.jsx";
import {
  analyze,
  listAnalyses,
  readAnalysis,
  signOut,
  updateProfile,
  whoami,
} from "./api.js";

const today = () => new Date().toISOString().slice(0, 10);

/** How long the whole reasoning phase lasts, at the least.
 *
 *  A floor on the wait, not an addition to it. The step names are a replay —
 *  by the time the server has said which workers ran, they have run — so the
 *  time already spent waiting is time the trace has already had. What is left
 *  of this budget is what the replay gets.
 *
 *  Before this, the two were added: the request took its own time and then the
 *  steps took a fixed second each on top. Connecting §4.2[9] made that visible
 *  — synthesis really costs 1.2–1.8s, so an eight-second wait appeared for
 *  work that had finished in two.
 *
 *  The effect is that the screen's rhythm stays the same whether or not the
 *  language model is reachable. Only the share of it that is real changes.
 *
 *  The steps themselves are read from the execution plan the server really
 *  produced, so nothing is shown as running that did not run. */
const TRACE_MS = 3000;

/** No step passes faster than this, however little budget is left. A name that
 *  flashes is a name nobody read, and the trace exists to be read. */
const STEP_FLOOR_MS = 120;

/** Fallback for the request bar, in case the turn never reports its arrival.
 *
 *  The turn itself says when it has finished landing — its length depends on
 *  the sentence and on how many blocks the plan produced, so only it can know.
 *  This is the ceiling that keeps the bar from being stranded if that signal
 *  is missed. */
const WRITE_CEILING_MS = 4000;


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

/** Walk a step list, fitting the replay into whatever the wait has left.
 *
 *  `spent` is how long the request actually took. A slow answer has already
 *  shown the reader that work was happening, so its trace is brief; a fast one
 *  has shown nothing yet, so its trace takes the time. */
async function walk(steps, show, spent = 0) {
  const left = Math.max(0, TRACE_MS - spent);
  const each = Math.max(STEP_FLOOR_MS, left / Math.max(steps.length, 1));
  for (let index = 0; index < steps.length; index += 1) {
    show({ steps, index });
    await wait(each);
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
  const [facts, setFacts] = useState({
    cases: [{}],
    profile: {},
    declarations: [],
    quote: null,
  });
  const [result, setResult] = useState(null);
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(null);
  const [writing, setWriting] = useState(false);
  // Who the server says we are, or null. Signing in is not required — the
  // product answers anonymously — so this starts as "not yet asked" rather than
  // as "signed out", and the sign-in screen is somewhere you go, not a door you
  // are stopped at.
  const [account, setAccount] = useState(null);
  const [showSignIn, setShowSignIn] = useState(false);
  // Things that happened to no screen in particular. What belongs to a screen
  // stays on it: a failed analysis is a turn in the thread, a rejected password
  // sits by the password field.
  const [notices, setNotices] = useState([]);
  const [knownUnknowns, setKnownUnknowns] = useState([]);
  const [analysisHistory, setAnalysisHistory] = useState([]);
  const noticeId = useRef(0);

  function notify(text) {
    noticeId.current += 1;
    const id = noticeId.current;
    // Say a thing once. Retrying a failing request every few seconds would
    // otherwise stack the same sentence down the screen.
    setNotices((prev) =>
      prev.some((notice) => notice.text === text) ? prev : [...prev, { id, text }],
    );
  }

  // Ask once on load. A session that survived a refresh should not have to be
  // proved again by typing.
  useEffect(() => {
    let live = true;
    whoami()
      .then((found) => live && found && setAccount(found))
      .catch(() => {
        // Not the same as being signed out, and it must not look like it.
        if (live) notify("로그인 상태를 확인하지 못했습니다. 서버에 연결되지 않았습니다.");
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!account) {
      setAnalysisHistory([]);
      return;
    }
    let live = true;
    listAnalyses()
      .then((items) => live && setAnalysisHistory(items))
      .catch(() => live && notify("저장된 분석 이력을 불러오지 못했습니다."));
    return () => {
      live = false;
    };
    // The account id is the tenant boundary. A changed profile should not
    // refetch history; a changed tenant must.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account?.account_id]);
  const threadRef = useRef(null);
  const stick = useRef(true);

  /** The conversation continues where it left off, at the bottom.
   *
   *  A new turn is added below the last one and the view goes with it. This
   *  briefly anchored the newest question to the top of the view instead,
   *  which reads well for one exchange and badly for a conversation: every
   *  answer pushed the one before it out of sight, so the thread stopped
   *  looking like a thread. Following the foot keeps what was just said
   *  next to what is being said now.
   *
   *  Set scrollTop directly rather than scrollIntoView({behavior:"smooth"}):
   *  smooth scrolling does not run in a background tab, which left the thread
   *  pinned near the top with the newest answer out of sight. */
  useLayoutEffect(() => {
    const el = threadRef.current;
    if (!el || !stick.current) return;
    el.scrollTop = el.scrollHeight;
  }, [turns, busy]);

  /** Follow the exchange down as it arrives.
   *
   *  The jump above happens once, when the turn is added — at which point the
   *  turn is still empty. Everything that gives it height arrives over the next
   *  few seconds, and without this the answer grows past the bottom of the
   *  thread while the reader watches its first line.
   *
   *  It eases rather than pins, so the view moves at the pace the answer is
   *  being written instead of snapping on every word. And it only ever moves
   *  down to what is already off screen — an exchange that fits needs no
   *  scrolling at all, and gets none.
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

    // The thread's own box changes under it: the request panel appears above
    // the composer and takes 88px, the composer grows with a long draft. The
    // content did not move, so the follower has nothing to chase — but the
    // window onto it shrank, and what was at the bottom is now below it.
    // Measured 70px of the newest answer cut off this way, after the follower
    // had already settled and stopped.
    const refit = new ResizeObserver(() => {
      if (stick.current) el.scrollTop = el.scrollHeight;
    });
    refit.observe(el);
    el.addEventListener("wheel", release, { passive: true });
    el.addEventListener("touchmove", release, { passive: true });
    el.addEventListener("keydown", release);

    const follow = setInterval(() => {
      if (!stick.current) {
        clearInterval(follow);
        return;
      }
      const delta = el.scrollHeight - el.clientHeight - el.scrollTop;
      // A proportional ease approaches the foot without reaching it, so the
      // last pixel is closed by the floor rather than by the curve. Without
      // one it crawls: from three pixels away, sixteen percent at a time.
      if (delta <= 1) {
        if (!busy && !writing) clearInterval(follow);
        return;
      }
      el.scrollTop += Math.max(delta * 0.16, 1.5);
    }, 16);

    return () => {
      clearInterval(follow);
      refit.disconnect();
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
      ? [
          ...facts.cases.slice(0, -1),
          {
            ...facts.cases.at(-1),
            ...patch.case,
            case_facts: {
              ...(facts.cases.at(-1)?.case_facts ?? {}),
              ...(patch.case.case_facts ?? {}),
            },
          },
        ]
      : facts.cases;
    const nextProfile = {
      ...facts.profile,
      ...(patch.profile ?? {}),
      company_facts: {
        ...(facts.profile.company_facts ?? {}),
        ...(patch.profile?.company_facts ?? {}),
      },
    };
    const nextDeclarations = patch.declaration
      ? mergeDeclaration(facts.declarations, patch.declaration)
      : facts.declarations;
    const nextQuote = patch.quote ?? facts.quote ?? null;
    setFacts({
      cases: nextCases,
      profile: nextProfile,
      declarations: nextDeclarations,
      quote: nextQuote,
    });

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
      const started = performance.now();
      if (account && Object.keys(patch.profile?.company_facts ?? {}).length > 0) {
        const updated = await updateProfile(patch.profile.company_facts);
        setAccount(updated);
      }
      const data = await analyze({
        cases: nextCases,
        utterance,
        ...nextProfile,
        compliance_declarations: nextDeclarations,
        as_of: today(),
        ...(placement ? { placement } : {}),
        ...(nextQuote ? { forward_quote: nextQuote } : {}),
      });
      const spent = performance.now() - started;
      // Company facts are not sent from here when signed in. The server reads
      // them from the session, so the screen cannot show one company while the
      // analysis runs for another.

      if (data.status === "needs_placement") {
        await walk(stepsForAsk(data, utterance), setThinking, spent);
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
        await walk(stepsFor(data.result), setThinking, spent);

        // The server is the authority on how many trades there are now; it
        // just decided whether the sentence added one.
        setFacts((prev) => ({
          ...prev,
          cases: data.result.trade_timeline.map((trade, index) => ({
            ...(prev.cases[index] ?? {}),
            ...trade,
          })),
        }));
        setResult(data.result);
        if (data.analysis_run_id) {
          listAnalyses()
            .then(setAnalysisHistory)
            .catch(() => notify("방금 분석은 저장됐지만 이력 목록을 갱신하지 못했습니다."));
        }
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
        await walk(stepsForAsk(data, utterance), setThinking, spent);
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
      <Nav
        onHome={() => {
          setShowSignIn(false);
          setView("entry");
        }}
        account={account}
        signingIn={showSignIn}
        onSignIn={() => setShowSignIn(true)}
        onSignOut={async () => {
          try {
            await signOut();
            setAccount(null);
            setAnalysisHistory([]);
          } catch {
            // The session is still open on the server. Showing a signed-out
            // screen over it would be the screen lying about the state that
            // matters most here.
            notify("로그아웃하지 못했습니다. 세션이 아직 열려 있습니다.");
          }
        }}
        analyses={analysisHistory}
        onOpenAnalysis={async (runId) => {
          try {
            const stored = await readAnalysis(runId);
            setResult(stored.result);
            setTurns([{
              who: "agent",
              kind: "result",
              result: stored.result,
              heard: {},
              spoken: false,
            }]);
            setView("work");
          } catch (error) {
            notify(error.message);
          }
        }}
      />
      <Notices
        notices={notices}
        onDismiss={(id) =>
          setNotices((prev) => prev.filter((notice) => notice.id !== id))
        }
      />
      {showSignIn && !account ? (
        <Login
          onSignIn={(who) => {
            setAccount(who);
            setShowSignIn(false);
          }}
        />
      ) : (
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
              account={account}
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
                  missingInputs={(result?.missing_input_queue ?? []).filter(
                    (item) => !knownUnknowns.includes(item.field),
                  )}
                  quoteInputs={
                    result?.hedge_analysis
                      ? []
                      : result?.required_inputs?.quote ?? []
                  }
                  onSlot={(patch, said) => send(null, patch, null, said)}
                  onUnknown={(field) =>
                    setKnownUnknowns((current) =>
                      current.includes(field) ? current : [...current, field],
                    )
                  }
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
      )}
    </>
  );
}

function mergeDeclaration(declarations, patch) {
  const index = declarations.findIndex(
    (item) => item.case_index === patch.case_index,
  );
  const previous =
    index >= 0
      ? declarations[index]
      : { case_index: patch.case_index, confirmed: true };
  const merged = { ...previous, ...patch, confirmed: true };
  if (index < 0) return [...declarations, merged];
  return declarations.map((item, itemIndex) =>
    itemIndex === index ? merged : item,
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
