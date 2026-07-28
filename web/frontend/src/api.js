/** What the server is running on, for the entry badge. */
export async function health() {
  const response = await fetch("/api/health");
  if (!response.ok) throw new Error(`서버가 ${response.status}로 응답했습니다.`);
  return response.json();
}

/** The one call this app makes to get an answer. */
export async function analyze(body) {
  const response = await fetch("/api/analyze", {
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
 *  signed in is the server's answer, not a flag the client sets about itself. */
export async function whoami() {
  const response = await fetch("/api/auth/me");
  if (!response.ok) return null;
  return (await response.json()).account;
}

export async function signIn(email, password) {
  const response = await fetch("/api/auth/login", {
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

export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST" });
}

export const won = (value) =>
  value === null || value === undefined || value === ""
    ? "—"
    : Number(value).toLocaleString("ko-KR");

export const pct = (value, digits = 1) =>
  value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;
