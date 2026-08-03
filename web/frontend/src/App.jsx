import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Nav from "./Nav.jsx";
import Entry from "./Entry.jsx";
import Thread from "./Thread.jsx";
import AskBar from "./AskBar.jsx";
import Login from "./Login.jsx";
import Notices from "./Notices.jsx";
import { analyze, signOut, whoami, SIGN_IN_OPEN } from "./api.js";
import {
  forget as forgetSession,
  load as loadSession,
  save as saveSession,
} from "./session.js";

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
/** 로그인 스위치는 `api.js`에 있습니다 — 화면에서 버튼을 치우는 것과 요청에
 *  자격 증명을 싣지 않는 것이 함께 움직여야 하고, 둘 중 하나만 꺼지면 화면과
 *  서버가 서로 다른 사용자를 봅니다.
 *
 *  지우지 않고 스위치로 둔 것은 계정이 사라진 게 아니라 아직 쓰지 않는
 *  것이기 때문입니다. `Login.jsx`와 서버의 세션·계정 저장소는 그대로입니다.
 *
 *  §5.4가 읽는 기업 사실은 그동안 계정이 아니라 화면이 직접 묻습니다 —
 *  기업규모와 신용 상태를 되묻는 그 경로가 원래 비로그인 방문자의 것입니다. */
export default function App() {
  // What the last page load left behind, read once before the first render so
  // the screen never paints an empty thread it is about to replace.
  const [restored] = useState(loadSession);
  const [view, setView] = useState(restored?.view ?? "entry");
  const [turns, setTurns] = useState(restored?.turns ?? []);
  const [facts, setFacts] = useState(
    restored?.facts ?? {
      cases: [{}],
      profile: {},
      quote: null,
      stated: {},
      structure: {},
    },
  );
  const [result, setResult] = useState(restored?.result ?? null);
  // The question that was open when the page went away. Restored because it is
  // half of an exchange: dropping it would leave the answer above it asking
  // for something with nowhere to answer it.
  const [pending, setPending] = useState(restored?.pending ?? null);
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

  // Written after each change rather than on unload: `beforeunload` does not
  // fire reliably on mobile, and a tab that is killed rather than closed would
  // take the whole conversation with it.
  //
  // Only what the user told us and what came back. Not `busy`, `thinking` or
  // `writing` — those describe a request that is no longer in flight, and
  // restoring them would open the page onto a spinner for work nobody is
  // doing.
  useEffect(() => {
    saveSession({ view, turns, facts, result, pending });
  }, [view, turns, facts, result, pending]);

  // Ask once on load. A session that survived a refresh should not have to be
  // proved again by typing.
  useEffect(() => {
    if (!SIGN_IN_OPEN) return;
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
  const threadRef = useRef(null);
  const stick = useRef(true);
  //: The last sentence the user wrote. Panel answers carry values and no
  //: words, and the answer has to stay about what was asked.
  const subject = useRef(null);

  /** Put the conversation down and start again.
   *
   *  Distinct from clicking the wordmark, which goes to the opening screen and
   *  keeps everything — a company that scrolled up to read the first answer
   *  must not lose the fourth. This is the other intention, and it needs its
   *  own control rather than being a longer press on the same one.
   *
   *  Everything the user told us goes: the trades, the company facts, the
   *  quote, the structure they declared, and the answers the rules asked for.
   *  Keeping any of it would make the next answer rest on something the reader
   *  can no longer see, which is the one thing a reset must not leave behind.
   *
   *  No confirmation step. What is lost is a conversation the user can retype
   *  in a sentence, and this is the control a demo reaches for between runs —
   *  a dialog there costs more than the mistake it prevents. It sits in the
   *  bar rather than beside the composer so it is not next to what is clicked
   *  every turn.
   */
  function startOver() {
    forgetSession();
    setTurns([]);
    setFacts({ cases: [{}], profile: {}, quote: null, stated: {}, structure: {} });
    setResult(null);
    setPending(null);
    setThinking(null);
    setWriting(false);
    setBusy(false);
    setNotices([]);
    subject.current = null;
    stick.current = true;
    setView("entry");
  }

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
      ? [...facts.cases.slice(0, -1), { ...facts.cases.at(-1), ...patch.case }]
      : facts.cases;
    const nextProfile = { ...facts.profile, ...(patch.profile ?? {}) };
    // The quote is remembered like everything else the user has told us: the
    // server is stateless, so it has to be resent with each turn or the hedge
    // would vanish the moment anything else was said.
    const nextQuote = patch.quote ?? facts.quote ?? null;
    // Answers to the rules' own questions accumulate the same way. The server
    // is stateless, so a grade stated three turns ago has to travel with every
    // request or the judgement it opened would close again.
    const nextStated = { ...facts.stated, ...(patch.facts ?? {}) };
    setFacts({
      cases: nextCases,
      profile: nextProfile,
      quote: nextQuote,
      stated: nextStated,
      structure: facts.structure ?? {},
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
    // The last sentence the user actually wrote, kept as the conversation's
    // standing subject. A follow-up rides on it — 「왜?」 and 「그럼?」 are made
    // of pointing words and name nothing on their own.
    //
    // Sent with the new sentence rather than instead of it, and the server
    // decides which to read: whether a sentence stands on its own is a reading
    // of that sentence, and this side does not do readings.
    const standing = subject.current;
    if (utterance) subject.current = utterance;
    if (spoken) say({ who: "user", text: spoken });
    setView("work");
    setBusy(true);

    try {
      const started = performance.now();
      const data = await analyze({
        cases: nextCases.map(asStated),
        utterance,
        // What the conversation is still about. A panel answer carries values
        // and no words, and the server was reading intent from that blank —
        // so the judgement the user had just supplied a fact for closed
        // itself as it arrived and the funnel started asking again.
        ...(standing ? { asked_about: standing } : {}),
        ...nextProfile,
        as_of: today(),
        ...(placement ? { placement } : {}),
        ...(nextQuote ? { forward_quote: nextQuote } : {}),
        ...(Object.keys(nextStated).length > 0 ? { stated_facts: nextStated } : {}),
        // What earlier sentences established about the trade structure. The
        // server reads 상계 out of the sentence, and a follow-up has no
        // sentence to read it from — so it travels with the trade, and this
        // turn's words still win over it.
        ...(Object.keys(facts.structure ?? {}).length > 0
          ? { declared_structure: facts.structure }
          : {}),
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
          cases: data.result.trade_timeline,
          // The server is the authority on what has been declared: it read the
          // sentence, and it merged this turn's reading over what we sent.
          structure: data.result.declared_structure ?? prev.structure,
        }));
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
      } else if (data.status === "said") {
        // A greeting, a question about the product, or a subject that holds
        // without a trade. No worker ran and nothing was judged, so there is
        // no request panel to open — clearing `pending` matters, or the
        // amount field from a previous turn stays on screen asking for a
        // number this turn never needed.
        await walk([], setThinking, spent);
        setPending(null);
        say({ who: "agent", kind: "said", ask: data });
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
        //: 지울 대화가 있을 때만 보입니다. 빈 화면에서 「새 대화」는 아무것도
        //: 하지 않는 버튼이고, 아무것도 하지 않는 버튼은 눌러 본 사람에게
        //: 제품이 고장 난 것처럼 보입니다.
        onStartOver={turns.length > 0 ? startOver : null}
        signInOpen={SIGN_IN_OPEN}
        signingIn={showSignIn}
        onSignIn={() => setShowSignIn(true)}
        onSignOut={async () => {
          try {
            await signOut();
            setAccount(null);
          } catch {
            // The session is still open on the server. Showing a signed-out
            // screen over it would be the screen lying about the state that
            // matters most here.
            notify("로그아웃하지 못했습니다. 세션이 아직 열려 있습니다.");
          }
        }}
      />
      <Notices
        notices={notices}
        onDismiss={(id) =>
          setNotices((prev) => prev.filter((notice) => notice.id !== id))
        }
      />
      {SIGN_IN_OPEN && showSignIn && !account ? (
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
                  /* The panel opens only for the worker this turn is asking
                     about. §4.2[5]'s inputs are still named in the hedge fold
                     whatever was asked — but a panel is a demand, and a
                     company that asked whether its netting is reportable was
                     being shown two boxes for its operating profit. */
                  requiredInputs={
                    result?.hedge_analysis || result?.asking_for !== "hedge"
                      ? []
                      : result?.required_inputs?.hedge ?? []
                  }
                  quoteInputs={
                    result?.hedge_analysis || result?.asking_for !== "hedge"
                      ? []
                      : result?.required_inputs?.quote ?? []
                  }
                  profileInputs={
                    result?.asking_for === "support"
                      ? result?.required_inputs?.profile ?? []
                      : []
                  }
                  askNote={
                    // 왜 묻는지. §4.2[2]가 워커를 건너뛰며 남긴 이유 그대로이고,
                    // 지금 열려 있는 패널의 것만 가져옵니다 — 패널이 무엇을
                    // 묻는지는 라벨이 말하고, 답하면 무엇이 열리는지는 이것이
                    // 말합니다. 전에는 같은 문장이 패널 위에 따로 서 있어서
                    // 같은 요청이 연달아 두 번이었습니다.
                    result?.workers?.skipped?.[result?.asking_for] ?? null
                  }
                  factInputs={
                    // Not gated on `asking_for`: these exist because a rule
                    // that already ran named them, and each one says which
                    // product it opens — so an offer about 지원제도 under a
                    // question about 신고의무 is legible, not a demand.
                    result?.required_inputs?.facts ?? []
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
      )}
    </>
  );
}

/** 서버가 정하는 것은 돌려보내지 않습니다.
 *
 *  거래 목록은 답에서 온 `trade_timeline`을 그대로 다시 싣는데, 그 행에는
 *  §4.2[1]이 매긴 `case_id`가 함께 옵니다. 요청 모델이 모르는 필드를 거부하기
 *  시작하면서 이것이 422로 돌아왔고, 그 거절이 옳습니다 — case_id는 인테이크가
 *  결정론적으로 붙이는 식별자이고, 클라이언트가 보낸 값을 받아 주면 화면이
 *  패킷 안의 신원을 고를 수 있게 됩니다. 사용자가 말한 것만 올려 보냅니다. */
const SERVER_OWNED = ["case_id"];

function asStated(trade) {
  const stated = { ...(trade ?? {}) };
  for (const field of SERVER_OWNED) delete stated[field];
  return stated;
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
