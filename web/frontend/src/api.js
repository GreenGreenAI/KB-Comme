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

export async function createConsultationHandoff(runId) {
  const response = await ask(
    `/api/analyses/${encodeURIComponent(runId)}/consultation-handoff`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        consent: true,
        target_bank: "KB_KOOKMIN_BANK",
      }),
    },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(
      payload?.detail?.reason ?? "은행 상담 패킷을 준비하지 못했습니다.",
    );
  }
  return response.json();
}

export async function readConsultation(runId) {
  const response = await ask(
    `/api/analyses/${encodeURIComponent(runId)}/consultation`,
  );
  if (!response.ok) throw new Error("상담 진행상태를 불러오지 못했습니다.");
  return (await response.json()).consultation;
}

export async function recordConsultationEvent(runId, status, note = "") {
  const requestedItems = status === "additional_information_requested"
    ? note.split(/[,\n]/).map((item) => item.trim()).filter(Boolean)
    : [];
  const response = await ask(
    `/api/analyses/${encodeURIComponent(runId)}/consultation-events`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        note,
        requested_items: requestedItems,
      }),
    },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail?.reason ?? "상담 진행상태를 기록하지 못했습니다.");
  }
  return (await response.json()).consultation;
}

async function documentRequest(url, init, fallback) {
  const response = await ask(url, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail?.reason ?? fallback);
  }
  return response.json();
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("문서 파일을 읽지 못했습니다."));
    reader.onload = () => {
      const encoded = String(reader.result).split(",", 2)[1];
      if (!encoded) {
        reject(new Error("문서 파일을 읽지 못했습니다."));
        return;
      }
      resolve(encoded);
    };
    reader.readAsDataURL(file);
  });
}

export async function uploadTradeDocument(caseId, file) {
  const contentBase64 = await fileAsBase64(file);
  const payload = await documentRequest(
    `/api/trade-cases/${encodeURIComponent(caseId)}/documents`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        content_base64: contentBase64,
      }),
    },
    "문서를 업로드하지 못했습니다.",
  );
  return payload.document;
}

export async function listTradeDocuments(caseId) {
  const payload = await documentRequest(
    `/api/trade-cases/${encodeURIComponent(caseId)}/documents`,
    undefined,
    "문서 목록을 불러오지 못했습니다.",
  );
  return payload.documents;
}

export async function confirmDocumentFields(documentId, fields) {
  const payload = await documentRequest(
    `/api/documents/${encodeURIComponent(documentId)}/confirm-fields`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fields }),
    },
    "추출 필드를 확인 저장하지 못했습니다.",
  );
  return payload.document;
}

export async function checkTradeDocuments(caseId, expectedFields) {
  return documentRequest(
    `/api/trade-cases/${encodeURIComponent(caseId)}/document-check`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_fields: expectedFields }),
    },
    "문서 정합성을 검사하지 못했습니다.",
  );
}

export const won = (value) =>
  value === null || value === undefined || value === ""
    ? "—"
    : Number(value).toLocaleString("ko-KR");

export const pct = (value, digits = 1) =>
  value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;
