/** The one call this app makes to get an answer. */
/** 로그인을 잠시 닫아 둡니다 — 지금은 비로그인으로만 씁니다.
 *
 *  화면에서 로그인 버튼만 치우는 것으로는 부족합니다. 세션 쿠키는 브라우저에
 *  남아 있고, 그대로 두면 계정 없는 화면이 계정의 기업 사실로 판정된 답을
 *  받습니다 — 화면과 서버가 서로 다른 사용자를 보는 상태입니다.
 *
 *  그래서 닫혀 있는 동안에는 자격 증명을 아예 보내지 않습니다(`omit`).
 *  로그아웃이 아니라 사용하지 않는 것이라, 서버의 세션은 건드리지 않고
 *  이 값을 `true`로 되돌리면 그대로 다시 쓰입니다. */
export const SIGN_IN_OPEN = false;

//: 계정을 쓰지 않는 동안에는 쿠키를 실어 보내지 않습니다.
const CREDENTIALS = SIGN_IN_OPEN ? "same-origin" : "omit";

/** Fetch, with the browser's own failure translated.
 *
 *  A dead server makes `fetch` reject with "Failed to fetch" — English, and
 *  about the transport rather than about anything the reader did. That string
 *  was reaching the screen as the agent's reply.
 */
async function ask(url, init) {
  try {
    return await fetch(url, init);
  } catch {
    throw new Error("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  }
}

export async function analyze(body) {
  const response = await ask("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: CREDENTIALS,
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.reason ?? `서버가 ${response.status}로 응답했습니다.`;
    throw new Error(message);
  }
  return response.json();
}

/** Who the server says we are. The screen asks rather than remembering — being
 *  signed in is the server's answer, not a flag the client sets about itself.
 *
 *  A failure here throws rather than returning null. Not being signed in and
 *  not being able to ask are different facts, and collapsing them meant a dead
 *  server looked exactly like a signed-out browser: the screen quietly dropped
 *  the account and said nothing. */
export async function whoami() {
  const response = await ask("/api/auth/me", { credentials: CREDENTIALS });
  if (!response.ok) throw new Error(`서버가 ${response.status}로 응답했습니다.`);
  return (await response.json()).account;
}

export async function signIn(email, password) {
  const response = await ask("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: CREDENTIALS,
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail?.reason ?? "로그인하지 못했습니다.");
  }
  return (await response.json()).account;
}

/** Signing out is the server's to do. If it did not, say so — clearing the
 *  account here anyway would show a signed-out screen over a session that is
 *  still valid to anyone holding the cookie. */
export async function signOut() {
  const response = await ask("/api/auth/logout", {
    method: "POST",
    credentials: CREDENTIALS,
  });
  if (!response.ok) throw new Error(`서버가 ${response.status}로 응답했습니다.`);
}

export const won = (value) =>
  value === null || value === undefined || value === ""
    ? "—"
    : Number(value).toLocaleString("ko-KR");

export const pct = (value, digits = 1) =>
  value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;
