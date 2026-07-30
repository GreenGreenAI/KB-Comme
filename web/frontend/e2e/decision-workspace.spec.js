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

test("a signed-in tenant reviews an extracted trade document", async ({ page }) => {
  const extracted = {
    document_id: "DOC-E2E",
    case_id: "EXPORT-001",
    filename: "invoice.txt",
    content_type: "text/plain",
    byte_size: 80,
    content_hash: "sha256:document",
    document_type: "commercial_invoice",
    extraction_state: "extracted",
    created_at: "2026-07-29T00:00:00+09:00",
    extraction: {
      issues: [],
      fields: [{
        field_name: "amount",
        extracted_value: "100,000",
        normalized_value: "100000",
        confidence: 0.96,
        location: { page: null, line: 3, start: 8, end: 15 },
        confirmed: false,
        confirmed_value: null,
      }],
    },
  };
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/auth/me") {
      await route.fulfill({
        json: {
          account: {
            account_id: "ACCOUNT-E2E",
            organization_id: "COMPANY-E2E",
            role: "company_admin",
            email: "e2e@example.com",
            company_name: "E2E 기업",
            facts: {},
          },
        },
      });
      return;
    }
    if (path === "/api/analyses") {
      await route.fulfill({ json: { analyses: [] } });
      return;
    }
    if (path === "/api/analyze") {
      await route.fulfill({
        json: {
          status: "ready",
          understood: {},
          analysis_run_id: "RUN-E2E",
          result,
        },
      });
      return;
    }
    if (path === "/api/trade-cases/EXPORT-001/documents") {
      await route.fulfill({
        json: request.method() === "GET"
          ? { documents: [] }
          : { document: extracted },
      });
      return;
    }
    if (path === "/api/documents/DOC-E2E/confirm-fields") {
      await route.fulfill({
        json: {
          document: {
            ...extracted,
            extraction: {
              ...extracted.extraction,
              fields: [{
                ...extracted.extraction.fields[0],
                confirmed: true,
                confirmed_value: "99000",
              }],
            },
          },
        },
      });
      return;
    }
    if (path === "/api/trade-cases/EXPORT-001/document-check") {
      await route.fulfill({
        json: {
          case_id: "EXPORT-001",
          document_count: 1,
          document_types: ["commercial_invoice"],
          review_required: true,
          findings: [{
            kind: "trade_document_mismatch",
            field: "amount",
            reason: "확정 거래 정보와 문서 값이 일치하지 않습니다.",
          }],
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
  await expect(page.getByRole("heading", { name: "거래 문서 검토" })).toBeVisible();

  await page.getByLabel("문서 선택").setInputFiles({
    name: "invoice.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Commercial Invoice\nAmount: USD 100000"),
  });
  await page.getByRole("button", { name: "업로드·추출" }).click();
  await expect(page.getByText("상업송장")).toBeVisible();
  await page.getByLabel(/금액/).fill("99000");
  await page.getByRole("button", { name: "추출 필드 확인 저장" }).click();
  await page.getByRole("button", { name: "거래·문서 정합성 검사" }).click();
  await expect(page.getByText("사람의 확인이 필요한 불일치")).toBeVisible();
});
