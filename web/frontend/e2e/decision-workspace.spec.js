import { expect, test } from "@playwright/test";

const result = {
  summary: "거래 분석이 완료되었습니다.",
  packet_id: "decision:test",
  company_profile: {
    company_id: "COMPANY-ANONYMOUS",
    company_name: "미입력 기업",
    is_sme: true,
    country_code: "KR",
    facts: { "company.size": "small" },
  },
  trade_timeline: [{
    case_id: "EXPORT-001",
    direction: "export",
    currency: "USD",
    amount: "100000",
    expected_payment_date: "2026-10-24",
    payment_method: "TT",
  }],
  cashflow_analysis: {
    net_exposure: [{ currency: "USD", amount: "100000" }],
    funding_gap: [{ currency: "USD", peak_amount: "0" }],
    natural_hedge_amount: [{ currency: "USD", amount: "0" }],
    maturity_matched_amount: [{ currency: "USD", amount: "0" }],
  },
  market_scenario: null,
  hedge_analysis: null,
  support_candidates: [{
    subject_id: "EXPORT-001",
    rule_id: "KSURE-FX",
    title: "환변동보험 후보",
    status: "insufficient_information",
    reasons: ["missing fact: company.credit_issue_free"],
    missing_fields: ["company.credit_issue_free"],
    source_ids: ["KSURE_FX_INSURANCE_ELIGIBILITY"],
  }],
  excluded_candidates: [],
  filing_obligations: [],
  risk_findings: [],
  next_actions: [],
  missing_information: [],
  missing_input_queue: [{
    field: "company.credit_issue_free",
    scope: "profile",
    subject_id: "EXPORT-001",
    worker: "support",
    reason: "환변동보험 후보",
  }],
  evidence: [{
    role: "official_source",
    source_id: "KSURE_FX_INSURANCE_ELIGIBILITY",
    title: "환변동보험 이용요건",
    organization: "한국무역보험공사",
    url: "https://www.ksure.or.kr/example",
    content_hash: "sha256:test",
  }],
  review_required: true,
  review_reasons: ["KSURE-FX: insufficient_information"],
  workers: {
    completed: ["exposure", "support", "compliance"],
    failed: {},
    skipped: { hedge: "기준 영업이익 필요" },
  },
  required_inputs: { hedge: [], all: ["company.credit_issue_free"] },
  execution_plan: {
    planned: ["exposure", "support", "compliance"],
    section_order: ["exposure", "support", "compliance", "hedge"],
  },
  calculation_versions: {
    formula_version: "exposure.v1",
    packet_schema_version: "1.6",
    input_fingerprint: "sha256:input",
    business_input_hash: "sha256:business",
    snapshots: [],
  },
};

test("a trade reaches the full decision workspace", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") {
      await route.fulfill({ json: { account: null } });
      return;
    }
    if (path === "/api/analyze") {
      await route.fulfill({
        json: {
          status: "ready",
          understood: {
            direction: "export",
            amount: "100000",
            expected_payment_date: "2026-10-24",
          },
          analysis_run_id: null,
          result,
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: {} });
  });

  await page.goto("/");
  await page.getByRole("button", {
    name: "10월 24일에 수출대금 10만 달러 받기로 했어요",
  }).click();

  await expect(page.getByRole("heading", { name: "지원제도 판정" })).toBeVisible();
  await expect(page.getByText("환변동보험 후보").first()).toBeVisible();
  await expect(page.getByLabel("검토 필요")).toBeVisible();
  await expect(page.getByRole("group", {
    name: "현재 신용 제한 사유가 없나요?",
  })).toBeVisible();

  await page.getByText("근거와 재현 정보").click();
  await expect(page.getByRole("link", { name: "공식 출처 열기" })).toBeVisible();
});
