import { useEffect, useState } from "react";

/** Kept in step with the .notice animation in styles.css. */
const ENTER_MS = 320;

/** Things that happened to no screen in particular.
 *
 *  Most of what this product has to say belongs somewhere: a failed analysis is
 *  a turn in the conversation, because the user asked something and did not get
 *  an answer, and deleting that would leave a question with no reply under it.
 *  A rejected password belongs beside the password field, where the hand is.
 *
 *  What is left over is everything that happened between the browser and the
 *  server without a screen to own it — a session that could not be checked, a
 *  sign-out the server never confirmed. Those used to be silent, because there
 *  was nowhere to put them. This is that place.
 *
 *  They do not time out. A notice that removes itself is a notice the reader
 *  can miss entirely by looking away, and everything here is something that
 *  went wrong and stayed wrong.
 */
export default function Notices({ notices, onDismiss }) {
  if (notices.length === 0) return null;
  return (
    <div className="notices">
      {notices.map((notice) => (
        <Notice key={notice.id} notice={notice} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function Notice({ notice, onDismiss }) {
  // The class comes off once the fade has had its time. An animation that is
  // applied but never advances holds its opening frame, and an opening frame at
  // zero opacity is a warning nobody sees — the one failure mode a warning
  // cannot afford.
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(true), ENTER_MS + 60);
    return () => clearTimeout(timer);
  }, []);

  return (
    <div className={settled ? "notice" : "notice notice-in"} role="alert">
      <span>{notice.text}</span>
      <button type="button" onClick={() => onDismiss(notice.id)} aria-label="닫기">
        ✕
      </button>
    </div>
  );
}
