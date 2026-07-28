/** The one call this app makes to get an answer. */
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
  const response = await ask("/api/auth/me");
  if (!response.ok) throw new Error(`서버가 ${response.status}로 응답했습니다.`);
  return (await response.json()).account;
}

export async function signIn(email, password) {
  const response = await ask("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  const response = await ask("/api/auth/logout", { method: "POST" });
  if (!response.ok) throw new Error(`서버가 ${response.status}로 응답했습니다.`);
}

export async function updateProfile(facts) {
  const response = await ask("/api/auth/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ facts }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail?.reason ?? "기업 정보를 저장하지 못했습니다.");
  }
  return (await response.json()).account;
}

export async function listAnalyses() {
  const response = await ask("/api/analyses");
  if (!response.ok) throw new Error("저장된 분석을 불러오지 못했습니다.");
  return (await response.json()).analyses;
}

export async function readAnalysis(runId) {
  const response = await ask(`/api/analyses/${encodeURIComponent(runId)}`);
  if (!response.ok) throw new Error("저장된 분석을 불러오지 못했습니다.");
  return response.json();
}

export const won = (value) =>
  value === null || value === undefined || value === ""
    ? "—"
    : Number(value).toLocaleString("ko-KR");

export const pct = (value, digits = 1) =>
  value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;
