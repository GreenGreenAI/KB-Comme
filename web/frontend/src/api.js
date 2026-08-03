/** The one call this app makes to get an answer. */
/** 로그인을 잠시 닫아 둡니다 — 지금은 비로그인으로만 씁니다.
 *
 *  화면에서 로그인 버튼만 치우는 것으로는 부족합니다. 세션 쿠키는 브라우저에
 *  남아 있고, 그대로 두면 계정 없는 화면이 계정의 기업 사실로 판정된 답을
 *  받습니다 — 화면과 서버가 서로 다른 사용자를 보는 상태입니다.
 *
 *  그래서 닫혀 있는 동안에는 자격 증명을 아예 보내지 않습니다(`omit`).
 *  로그아웃이 아니라 사용하지 않는 것이라, 서버의 세션은 건드리지 않고
 *  이 값을 `true`로 되돌리면 그대로 다시 쓰입니다.
 *
 *  서버에도 같은 스위치가 있습니다 — `web/app.py`의 `SIGN_IN_OPEN`, 환경변수
 *  `TRADEFLOW_SIGN_IN`. 화면만 열면 로그인 화면이 404를 받고, 서버만 열면
 *  들어갈 문이 화면에 없습니다. 되돌릴 때는 둘 다입니다. */
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
    throw new Error(refused(await response.json().catch(() => null), response.status));
  }
  return response.json();
}

/** 서버가 왜 거절했는지, 읽을 수 있는 한 문장으로.
 *
 *  서버가 모르는 필드를 거부하기 시작하면서(422) 이 자리가 중요해졌습니다.
 *  FastAPI의 422 `detail`은 문자열도 `{reason}`도 아닌 목록이라 이전 코드는
 *  전부 「서버가 422로 응답했습니다」로 접었습니다 — 무엇이 거절됐는지 화면
 *  어디에도 없었습니다. 거절의 요점은 어느 필드가 문제인지이므로 그것을
 *  말합니다. */
function refused(payload, status) {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.reason) return detail.reason;
  if (Array.isArray(detail)) {
    // `loc`은 ["body", "cases", 0, "amount"]처럼 옵니다. 사람이 찾을 수 있는
    // 것은 마지막 조각이고, "body"는 어느 필드인지 말해 주지 않습니다.
    const fields = [
      ...new Set(
        detail
          .map((item) => (item?.loc ?? []).filter((part) => part !== "body").at(-1))
          .filter((part) => part !== undefined && part !== null),
      ),
    ];
    if (fields.length > 0) {
      return `서버가 요청을 거절했습니다 — 알 수 없거나 잘못된 필드: ${fields.join(" · ")}`;
    }
  }
  return `서버가 ${status}로 응답했습니다.`;
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
