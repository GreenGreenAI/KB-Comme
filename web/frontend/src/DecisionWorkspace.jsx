import { useState } from "react";
import { createConsultationHandoff } from "./api.js";
import DocumentPanel from "./DocumentPanel.jsx";

const STATUS = {
  eligible: "요건 충족",
  conditionally_eligible: "조건부 후보",
  not_eligible: "조건 불충족",
  insufficient_information: "정보 필요",
  expert_confirmation_required: "전문가 확인 필요",
  source_expired: "출처 갱신 필요",
  missing: "입력 필요",
  required: "필요",
  not_required: "불필요",
};

const FIELD = {
  "company.size": "기업 규모",
  "company.credit_issue_free": "신용 제한 사유 없음",
  "company.ksure_exporter_grade": "K-SURE 수출자 등급",
  "company.is_domestic": "국내 기업 여부",
  "payment.is_netting": "상계 거래 여부",
  "payment.is_third_party": "제3자 지급 여부",
  "payment.uses_mutual_account": "상호계산계정 사용 여부",
  "payment.uses_foreign_exchange_bank": "외국환은행 이용 여부",
  "trade.payment_term_days": "결제기간",
  "financing.purpose": "금융 목적",
  "financing.has_bank_consultation": "은행 상담 여부",
  "counterparty.country_restricted": "거래국 인수 제한 여부",
  "counterparty.ksure_importer_grade": "K-SURE 수입자 등급",
  "market_data.ecos_usd_krw": "ECOS USD/KRW 시장 데이터",
  baseline_profit: "기준 영업이익",
  profit_floor: "목표 손익 하한",
};

const AUTHORITY = {
  ksure: "한국무역보험공사",
  ksure_and_financial_institution: "한국무역보험공사·금융기관",
  bok: "한국은행",
  designated_foreign_exchange_bank: "지정 외국환은행",
};

const ACTION = {
  consult_and_apply_for_ksure_product: "K-SURE 상담 후 상품 신청",
  consult_and_apply_for_preshipment_guarantee: "선적전 수출신용보증 상담·신청",
  file_report: "신고서 제출",
  consult_designated_bank: "지정 외국환은행과 신고 절차 확인",
};

const present = (value) =>
  value === null || value === undefined || value === "" ? "미정" : String(value);

const label = (table, value) => table[value] ?? present(value);

function workerState(result, worker) {
  if (result.workers?.completed?.includes(worker)) return "completed";
  if (result.workers?.failed?.[worker]) return "failed";
  return "skipped";
}

function EmptyState({ result, worker, empty }) {
  const state = workerState(result, worker);
  const message =
    state === "completed"
      ? empty
      : state === "failed"
        ? `실행 실패 · ${result.workers.failed[worker]}`
        : `미실행 · ${result.workers?.skipped?.[worker] ?? "필요한 입력이 없습니다"}`;
  return <p className={`decision-empty ${state}`}>{message}</p>;
}

export function ReviewBanner({ result }) {
  if (!result.review_required) {
    return (
      <aside className="review-banner clear" aria-label="검토 상태">
        자동 검토 범위에서 추가 확인 사유가 없습니다.
      </aside>
    );
  }
  return (
    <aside className="review-banner required" aria-label="검토 필요">
      <b>사람의 검토가 필요합니다</b>
      <span>
        규정·자격·출처 상태를 자동 확정하지 않은 항목이 {result.review_reasons?.length ?? 0}건 있습니다.
      </span>
      <details>
        <summary>검토 사유 보기</summary>
        <ul>
          {(result.review_reasons ?? []).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </details>
    </aside>
  );
}

function amount(value, unit) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return present(value);
  return `${unit ? `${unit} ` : ""}${numeric.toLocaleString("ko-KR")}`;
}

export function NextDecisiveQuestion({ result }) {
  const question = result.next_decisive_questions?.[0];
  if (!question) return null;
  const preview = question.impact_preview;
  return (
    <section className="decision-signature decisive-question" aria-labelledby="decisive-title">
      <div className="signature-kicker">Next Decisive Question</div>
      <h3 id="decisive-title">무엇이 결과를 바꾸나요?</h3>
      <p className="signature-question">{question.question}</p>
      <p>{question.reason}</p>
      {preview ? (
        <div className="impact-preview">
          <span>현재 {question.changes[0]}</span>
          <strong>{amount(preview.current, preview.currency)}</strong>
        </div>
      ) : null}
      <div className="impact-tags" aria-label="변경되는 결과">
        {question.changes.map((item) => <span key={item}>{item}</span>)}
      </div>
      <small>아래 입력창에 답하면 변경된 부분만 다시 계산합니다.</small>
    </section>
  );
}

function deltaValue(change, value) {
  if (change.kind === "cashflow_metric") return amount(value, change.unit);
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : "없음";
  return STATUS[value] ?? present(value);
}

export function DecisionDelta({ result }) {
  const delta = result.decision_delta;
  if (!delta) return null;
  return (
    <section className="decision-signature decision-delta" aria-labelledby="delta-title">
      <div className="signature-kicker">Decision Delta</div>
      <h3 id="delta-title">이번 답변으로 달라진 결정</h3>
      {!delta.changed ? (
        <p>판정과 계산 결과에 실질적인 변화가 없습니다.</p>
      ) : (
        <div className="delta-list">
          {delta.changes.map((change) => (
            <article key={`${change.kind}:${change.subject_id}:${change.rule_id ?? change.metric}`}>
              <span>{change.label}</span>
              <div>
                <del>{deltaValue(change, change.before)}</del>
                <b aria-hidden="true">→</b>
                <strong>{deltaValue(change, change.after)}</strong>
              </div>
            </article>
          ))}
          {delta.resolved_questions.map((item) => (
            <article key={item.question_id} className="resolved-question">
              <span>해결된 확인사항</span>
              <strong>{item.question}</strong>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export function TradeTimeline({ trades = [] }) {
  if (trades.length === 0) return null;
  return (
    <section className="decision-section" aria-labelledby="trade-timeline-title">
      <h3 id="trade-timeline-title">거래 타임라인</h3>
      <ol className="trade-timeline">
        {trades.map((trade) => (
          <li key={trade.case_id}>
            <time dateTime={trade.expected_payment_date}>{trade.expected_payment_date}</time>
            <b>{trade.direction === "export" ? "수출 수취" : "수입 지급"}</b>
            <span>{Number(trade.amount).toLocaleString("ko-KR")} {trade.currency}</span>
            <small>{trade.payment_method}</small>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function CompanySummary({ profile }) {
  if (!profile) return null;
  const size = profile.facts?.["company.size"];
  const sizeLabel = {
    small: "중소기업",
    mid_sized: "중견기업",
    large: "대기업",
  }[size];
  return (
    <section className="company-summary" aria-label="분석 대상 기업">
      <div>
        <small>분석 대상</small>
        <b>{profile.company_name}</b>
      </div>
      <span>{sizeLabel ?? (profile.is_sme === true ? "중소기업" : "규모 미확인")}</span>
      <span>{profile.country_code ?? "소재지 미확인"}</span>
      <code>{profile.company_id}</code>
    </section>
  );
}

function DecisionCard({ item }) {
  const statusReason = {
    expert_confirmation_required: "공개 요건상 검토 후보이며 전문가 확인이 필요합니다.",
    insufficient_information: "추가 정보가 있어야 후보 여부를 판단할 수 있습니다.",
    conditionally_eligible: "표시된 선행 조건을 확인해야 다음 단계로 진행할 수 있습니다.",
    not_eligible: "현재 확인된 조건에서는 대상이 아닙니다.",
    source_expired: "근거 출처를 갱신한 뒤 다시 판단해야 합니다.",
  }[item.status];
  return (
    <article className={`decision-card status-${item.status}`}>
      <header>
        <b>{item.title}</b>
        <span className="decision-status">{label(STATUS, item.status)}</span>
      </header>
      <p>{statusReason || item.reasons?.join(" · ") || "판정 이유가 기록되지 않았습니다."}</p>
      {item.missing_fields?.length > 0 ? (
        <p className="decision-missing">
          필요한 정보: {item.missing_fields.map((field) => FIELD[field] ?? field).join(", ")}
        </p>
      ) : null}
      <small>근거: {item.source_ids?.join(", ") || "출처 미연결"}</small>
    </article>
  );
}

export function SupportCandidates({ result }) {
  const candidates = result.support_candidates ?? [];
  const excluded = result.excluded_candidates ?? [];
  return (
    <section className="decision-section" aria-labelledby="support-title">
      <h3 id="support-title">지원제도 판정</h3>
      {candidates.length > 0 ? (
        <div className="decision-list">
          {candidates.map((item) => <DecisionCard key={`${item.subject_id}:${item.rule_id}`} item={item} />)}
        </div>
      ) : (
        <EmptyState result={result} worker="support" empty="실행 결과, 표시할 지원제도 후보가 없습니다." />
      )}
      {excluded.length > 0 ? (
        <details className="decision-disclosure">
          <summary>조건 불충족 항목 {excluded.length}건</summary>
          <div className="decision-list">
            {excluded.map((item) => <DecisionCard key={`${item.subject_id}:${item.rule_id}`} item={item} />)}
          </div>
        </details>
      ) : null}
    </section>
  );
}

function ActionCard({ action, filing = false }) {
  return (
    <article className="action-card">
      <header>
        <b>{label(ACTION, action.action)}</b>
        {filing ? <span className="decision-status">신고 검토</span> : null}
      </header>
      <dl>
        <div><dt>담당</dt><dd>{label(AUTHORITY, action.authority)}</dd></div>
        <div><dt>기한</dt><dd>{action.deadline ?? action.timing ?? "사전 확인"}</dd></div>
        <div><dt>대상</dt><dd>{present(action.subject_id)}</dd></div>
      </dl>
      {action.requirements?.length > 0 ? (
        <p>선행조건: {action.requirements.map((item) => item.description ?? item.field ?? String(item)).join(", ")}</p>
      ) : null}
      {action.required_documents?.length > 0 ? (
        <p>필요서류: {action.required_documents.join(", ")}</p>
      ) : null}
      {action.steps?.length > 0 ? (
        <ol>{action.steps.map((step) => <li key={step}>{step}</li>)}</ol>
      ) : null}
    </article>
  );
}

export function ComplianceFindings({ result }) {
  const obligations = result.filing_obligations ?? [];
  const findings = result.risk_findings ?? [];
  return (
    <section className="decision-section" aria-labelledby="compliance-title">
      <h3 id="compliance-title">신고·규정 검토</h3>
      {obligations.length > 0 ? (
        <div className="action-list">
          {obligations.map((action, index) => (
            <ActionCard key={`${action.subject_id}:${action.action}:${index}`} action={action} filing />
          ))}
        </div>
      ) : findings.length > 0 ? (
        <div className="decision-list">
          {findings.map((item) => <DecisionCard key={`${item.subject_id}:${item.rule_id}`} item={item} />)}
        </div>
      ) : (
        <EmptyState
          result={result}
          worker="compliance"
          empty="실행 결과, 현재 입력에서 신고 검토사항이 발견되지 않았습니다."
        />
      )}
    </section>
  );
}

export function ActionPlan({ result }) {
  const actions = result.next_actions ?? [];
  return (
    <section className="decision-section action-plan" aria-labelledby="action-title">
      <h3 id="action-title">다음 행동</h3>
      {result.review_required ? (
        <p className="action-review">아래 행동은 자동 실행되지 않습니다. 담당 기관 또는 전문가 확인 후 진행하세요.</p>
      ) : null}
      {actions.length > 0 ? (
        <div className="action-list">
          {actions.map((action, index) => (
            <ActionCard key={`${action.subject_id}:${action.action}:${index}`} action={action} />
          ))}
        </div>
      ) : (
        <p className="decision-empty">확정된 실행 행동이 없습니다. 누락 정보를 보완하면 다시 판정합니다.</p>
      )}
    </section>
  );
}

export function MissingInputQueue({ result }) {
  const questions = result.user_questions ?? [];
  const fetches = result.system_fetches ?? [];
  const expertTasks = result.expert_tasks ?? [];
  const queue = (result.missing_input_queue ?? []).slice(0, 3);
  const hasPartitionedWork = questions.length > 0 || fetches.length > 0 || expertTasks.length > 0;
  if (!hasPartitionedWork && queue.length === 0 && (result.missing_information ?? []).length === 0) return null;
  return (
    <section className="decision-section" aria-labelledby="missing-title">
      <h3 id="missing-title">다음 판정을 여는 작업</h3>
      {hasPartitionedWork ? (
        <div className="work-queues">
          {questions.length > 0 ? (
            <div>
              <h4>고객 확인</h4>
              <ol className="missing-queue">
                {questions.map((item) => (
                  <li key={item.question_id}>
                    <b>{item.fields?.map((field) => FIELD[field] ?? field).join(", ")}</b>
                    <span>{item.question}</span>
                    <small>고객 답변 대기</small>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
          {fetches.length > 0 ? (
            <div>
              <h4>시스템 조회</h4>
              <ul className="missing-queue plain">
                {fetches.map((item) => (
                  <li key={`${item.capability_id}:${item.subject_id ?? "program"}`}>
                    <b>{FIELD[item.field] ?? item.field}</b>
                    <span>{item.reason}</span>
                    <small>{item.capability_id} · {item.status === "provider_unavailable" ? "연결 필요" : item.status}</small>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {expertTasks.length > 0 ? (
            <div>
              <h4>전문가 확인</h4>
              <ul className="missing-queue plain">
                {expertTasks.map((item) => (
                  <li key={item.task_id}>
                    <b>{item.title}</b>
                    <span>{item.reason}</span>
                    <small>{label(AUTHORITY, item.authority)}</small>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : queue.length > 0 ? (
        <ol className="missing-queue">
          {queue.map((item) => (
            <li key={`${item.subject_id ?? "program"}:${item.field}`}>
              <b>{FIELD[item.field] ?? item.field}</b>
              <span>{item.reason}</span>
              <small>{item.scope} · {item.worker} · unknown 유지</small>
            </li>
          ))}
        </ol>
      ) : (
        <ul className="missing-queue plain">
          {(result.missing_information ?? []).slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
    </section>
  );
}

export function CapabilityTrace({ result }) {
  const capabilities = result.capability_trace ?? [];
  if (capabilities.length === 0) return null;
  const statusLabel = {
    succeeded: "실행 완료",
    failed: "실행 실패",
    skipped: "미실행",
    authorized_not_executed: "실행 가능·미실행",
    blocked_consent: "동의 필요",
    provider_unavailable: "연결 필요",
  };
  return (
    <details className="decision-evidence capability-trace">
      <summary>시스템 실행 내역</summary>
      <ul className="missing-queue plain">
        {capabilities.map((item) => (
          <li key={item.capability_id}>
            <b>{item.capability_id}</b>
            <span>{statusLabel[item.status] ?? item.status}</span>
            {item.reason ? <small>{item.reason}</small> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function EvidenceSummary({ result }) {
  const evidence = result.evidence ?? [];
  const versions = result.calculation_versions ?? {};
  return (
    <details className="decision-evidence">
      <summary>근거와 재현 정보</summary>
      <div className="evidence-grid">
        {evidence.map((item, index) => (
          <article key={`${item.role}:${item.source_id ?? index}`}>
            <b>{item.title ?? item.detail ?? item.source_id ?? item.role}</b>
            <span>{item.organization ?? item.role}</span>
            {item.url ? <a href={item.url} target="_blank" rel="noreferrer">공식 출처 열기</a> : null}
            <small>
              관측 {item.observed_at ?? "해당 없음"} · 수집 {item.retrieved_at ?? "해당 없음"}
            </small>
            <code>{item.content_hash ?? item.formula_version ?? "hash 없음"}</code>
          </article>
        ))}
      </div>
      <dl className="repro">
        <div><dt>계산식</dt><dd>{versions.formula_version ?? "미기록"}</dd></div>
        <div><dt>패킷 스키마</dt><dd>{versions.packet_schema_version ?? "미기록"}</dd></div>
        <div><dt>입력 fingerprint</dt><dd>{versions.input_fingerprint ?? "미기록"}</dd></div>
        <div><dt>사업 입력 hash</dt><dd>{versions.business_input_hash ?? "미기록"}</dd></div>
      </dl>
    </details>
  );
}

export function ConsultationHandoff({ result, signedIn }) {
  const [consented, setConsented] = useState(false);
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");
  const runId = result.analysis_run_id;

  async function prepare() {
    if (!consented || !runId) return;
    setState("working");
    setError("");
    try {
      const packet = await createConsultationHandoff(runId);
      const blob = new Blob(
        [JSON.stringify(packet, null, 2)],
        { type: "application/json" },
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${packet.handoff_id}.json`;
      link.click();
      URL.revokeObjectURL(url);
      setState("ready");
    } catch (caught) {
      setError(caught.message);
      setState("idle");
    }
  }

  return (
    <section
      className="decision-section consultation-handoff"
      aria-labelledby="consultation-title"
    >
      <div className="signature-kicker">Decision Passport</div>
      <h3 id="consultation-title">KB국민은행 상담자료</h3>
      <p>
        사실·계산·규칙·공식 출처와 Decision Delta를 하나의 재현 가능한 자료로 묶습니다.
        현재는 은행 시스템에 자동 전송하지 않고 담당자에게 직접 전달합니다.
      </p>
      {!signedIn ? (
        <p className="decision-empty">
          로그인하면 분석 이력에 연결된 상담 패킷을 만들 수 있습니다.
        </p>
      ) : !runId ? (
        <p className="decision-empty">
          저장된 분석에서 상담 패킷을 만들 수 있습니다.
        </p>
      ) : (
        <>
          <label className="consultation-consent">
            <input
              type="checkbox"
              checked={consented}
              onChange={(event) => setConsented(event.target.checked)}
            />
            이 분석 정보를 무역금융 상담 목적으로 전달하는 데 동의합니다.
          </label>
          <button
            type="button"
            onClick={prepare}
            disabled={!consented || state === "working"}
          >
            {state === "working" ? "자료 준비 중" : "Decision Passport 내려받기"}
          </button>
          {state === "ready" ? (
            <p role="status">
              수동 인계용 패킷을 준비했습니다. 자동 전송된 정보는 없습니다.
            </p>
          ) : null}
          {error ? <p role="alert">{error}</p> : null}
        </>
      )}
    </section>
  );
}

export default function DecisionWorkspace({ result, signedIn = false }) {
  return (
    <div className="decision-workspace">
      <ReviewBanner result={result} />
      <DecisionDelta result={result} />
      <NextDecisiveQuestion result={result} />
      <CompanySummary profile={result.company_profile} />
      <TradeTimeline trades={result.trade_timeline ?? []} />
      <DocumentPanel trades={result.trade_timeline ?? []} signedIn={signedIn} />
      <SupportCandidates result={result} />
      <ComplianceFindings result={result} />
      <MissingInputQueue result={result} />
      <ActionPlan result={result} />
      <ConsultationHandoff result={result} signedIn={signedIn} />
      <CapabilityTrace result={result} />
      <EvidenceSummary result={result} />
    </div>
  );
}
