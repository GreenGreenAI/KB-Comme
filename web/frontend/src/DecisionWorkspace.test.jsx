import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import DecisionWorkspace, { ConsultationHandoff } from "./DecisionWorkspace.jsx";

const result = {
  company_profile: {
    company_id: "COMPANY-HANBIT",
    company_name: "한빛정밀",
    is_sme: true,
    country_code: "KR",
    facts: { "company.size": "small" },
  },
  trade_timeline: [
    {
      case_id: "EXPORT-001",
      direction: "export",
      amount: "100000",
      currency: "USD",
      expected_payment_date: "2026-10-24",
      payment_method: "TT",
    },
  ],
  support_candidates: [
    {
      subject_id: "EXPORT-001",
      rule_id: "KSURE-FX",
      title: "환변동보험 후보",
      status: "insufficient_information",
      reasons: ["missing fact: company.credit_issue_free"],
      missing_fields: ["company.credit_issue_free"],
      source_ids: ["KSURE_FX_INSURANCE_ELIGIBILITY"],
    },
  ],
  excluded_candidates: [],
  filing_obligations: [
    {
      subject_id: "EXPORT-001",
      action: "file_report",
      authority: "bok",
      deadline: "2026-08-31",
      requirements: [],
      required_documents: ["신고서", "계약서"],
      steps: ["한국은행에 사전 문의", "신고서 제출"],
    },
  ],
  risk_findings: [],
  next_actions: [
    {
      subject_id: "EXPORT-001",
      action: "file_report",
      authority: "bok",
      deadline: "2026-08-31",
      requirements: [],
      required_documents: ["신고서"],
      steps: ["신고서 제출"],
    },
  ],
  missing_input_queue: [
    {
      field: "company.credit_issue_free",
      scope: "profile",
      subject_id: "EXPORT-001",
      worker: "support",
      reason: "환변동보험 후보",
    },
  ],
  missing_information: [],
  user_questions: [
    {
      question_id: "credit_confirmation",
      fields: ["company.credit_issue_free"],
      question: "신용 제한 사유가 없는지 확인해 주세요.",
    },
  ],
  system_fetches: [
    {
      field: "counterparty.ksure_importer_grade",
      capability_id: "ksure.importer_grade.lookup.v1",
      subject_id: "EXPORT-001",
      status: "provider_unavailable",
      reason: "K-SURE 등급 조회가 필요합니다.",
    },
  ],
  expert_tasks: [
    {
      task_id: "EXPORT-001:KSURE-FX",
      title: "환변동보험 후보",
      authority: "ksure",
      reason: "전문가 확인 필요",
    },
  ],
  capability_trace: [
    {
      capability_id: "ksure.importer_grade.lookup.v1",
      status: "provider_unavailable",
      reason: "K-SURE provider is not configured",
    },
  ],
  evidence: [
    {
      role: "official_source",
      source_id: "KSURE_FX_INSURANCE_ELIGIBILITY",
      title: "환변동보험 이용요건",
      organization: "한국무역보험공사",
      url: "https://www.ksure.or.kr/example",
      retrieved_at: "2026-07-27T00:00:00+09:00",
      content_hash: "sha256:test",
    },
  ],
  calculation_versions: {
    formula_version: "exposure.v1",
    packet_schema_version: "1.6",
    input_fingerprint: "sha256:input",
    business_input_hash: "sha256:business",
  },
  next_decisive_questions: [{
    question_id: "liquidity.opening_balance.USD",
    field: "opening_balance_usd",
    fields: ["opening_balance_usd"],
    scope: "liquidity",
    subject_id: "USD",
    actor: "user",
    question: "현재 보유한 USD 외화잔액은 얼마인가요?",
    reason: "보유 외화만큼 최대 자금 공백이 줄어듭니다.",
    changes: ["최대 자금 공백"],
    impact_preview: { current: "60000", currency: "USD" },
  }],
  decision_delta: {
    changed: true,
    changes: [{
      kind: "cashflow_metric",
      metric: "funding_gap",
      label: "최대 자금 공백",
      subject_id: "USD",
      before: "60000",
      after: "40000",
      unit: "USD",
    }],
    resolved_questions: [],
  },
  review_required: true,
  review_reasons: ["KSURE-FX: insufficient_information"],
  workers: {
    completed: ["support", "compliance"],
    failed: {},
    skipped: {},
  },
};

describe("DecisionWorkspace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("renders the company, decisions, action owner, deadline and review state", () => {
    render(<DecisionWorkspace result={result} />);

    expect(screen.getByText("한빛정밀")).toBeInTheDocument();
    expect(screen.getAllByText("환변동보험 후보").length).toBeGreaterThan(0);
    expect(screen.getByText("정보 필요")).toBeInTheDocument();
    expect(screen.getAllByText("한국은행").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2026-08-31").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("검토 필요")).toHaveTextContent("사람의 검토가 필요합니다");
    expect(screen.getByRole("heading", { name: "무엇이 결과를 바꾸나요?" })).toBeInTheDocument();
    expect(screen.getByText("현재 보유한 USD 외화잔액은 얼마인가요?")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "이번 답변으로 달라진 결정" })).toBeInTheDocument();
    expect(screen.getAllByText("USD 60,000").length).toBeGreaterThan(0);
    expect(screen.getByText("USD 40,000")).toBeInTheDocument();
  });

  it("exposes official evidence and reproducibility within one disclosure", async () => {
    const user = userEvent.setup();
    render(<DecisionWorkspace result={result} />);

    await user.click(screen.getByText("근거와 재현 정보"));
    expect(screen.getByRole("link", { name: "공식 출처 열기" })).toHaveAttribute(
      "href",
      "https://www.ksure.or.kr/example",
    );
    expect(screen.getByText("sha256:input")).toBeInTheDocument();
  });

  it("separates customer questions, system fetches and expert tasks", () => {
    render(<DecisionWorkspace result={result} />);

    expect(screen.getByText("고객 확인")).toBeInTheDocument();
    expect(screen.getByText("시스템 조회")).toBeInTheDocument();
    expect(screen.getByText("전문가 확인", { selector: "h4" })).toBeInTheDocument();
    expect(screen.getAllByText("연결 필요", { exact: false }).length).toBeGreaterThan(0);
  });

  it("shows capability execution status without implying a provider call", async () => {
    const user = userEvent.setup();
    render(<DecisionWorkspace result={result} />);

    await user.click(screen.getByText("시스템 실행 내역"));
    expect(screen.getAllByText("ksure.importer_grade.lookup.v1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("연결 필요").length).toBeGreaterThan(0);
  });

  it("distinguishes a skipped worker from a completed empty result", () => {
    const skipped = {
      ...result,
      filing_obligations: [],
      risk_findings: [],
      workers: {
        completed: ["support"],
        failed: {},
        skipped: { compliance: "거래 구조 확인 필요" },
      },
    };
    render(<DecisionWorkspace result={skipped} />);
    expect(screen.getByText(/미실행 · 거래 구조 확인 필요/)).toBeInTheDocument();
    expect(screen.queryByText(/신고 검토사항이 발견되지 않았습니다/)).not.toBeInTheDocument();
  });

  it("requires consent and downloads a non-transmitting KB handoff packet", async () => {
    const user = userEvent.setup();
    const click = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        handoff: {
          handoff_id: "HANDOFF-test",
          state: "ready_for_manual_handoff",
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )));
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:test"),
      revokeObjectURL: vi.fn(),
    });
    const createElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      if (tag === "a") return { click };
      return createElement(tag);
    });
    render(
      <ConsultationHandoff
        result={{ ...result, analysis_run_id: "RUN-1" }}
        signedIn
      />,
    );

    const button = screen.getByRole("button", { name: "Decision Passport 내려받기" });
    expect(button).toBeDisabled();
    await user.click(screen.getByRole("checkbox"));
    await user.click(button);

    expect(fetch).toHaveBeenCalledWith(
      "/api/analyses/RUN-1/consultation-handoff",
      expect.objectContaining({ method: "POST" }),
    );
    expect(click).toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("자동 전송된 정보는 없습니다");
  });
});
