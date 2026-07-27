/** The one call this app makes. */
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

export const won = (value) =>
  value === null || value === undefined || value === ""
    ? "—"
    : Number(value).toLocaleString("ko-KR");

export const pct = (value, digits = 1) =>
  value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;
