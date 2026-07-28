import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import DecisionWorkspace from "./DecisionWorkspace.jsx";

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
  review_required: true,
  review_reasons: ["KSURE-FX: insufficient_information"],
  workers: {
    completed: ["support", "compliance"],
    failed: {},
    skipped: {},
  },
};

describe("DecisionWorkspace", () => {
  it("renders the company, decisions, action owner, deadline and review state", () => {
    render(<DecisionWorkspace result={result} />);

    expect(screen.getByText("한빛정밀")).toBeInTheDocument();
    expect(screen.getAllByText("환변동보험 후보").length).toBeGreaterThan(0);
    expect(screen.getByText("정보 필요")).toBeInTheDocument();
    expect(screen.getAllByText("한국은행").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2026-08-31").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("검토 필요")).toHaveTextContent("사람의 검토가 필요합니다");
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
});
