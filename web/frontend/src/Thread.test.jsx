import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ResultChangeSummary, ResultUpdate, resultChanges } from "./Thread.jsx";

function analysis({
  net = "100000",
  gap = "0",
  natural = "0",
  adverse = "1375.50",
  ratio = "0.40",
  trades = 1,
} = {}) {
  return {
    cashflow_analysis: {
      net_exposure: [{ amount: net }],
      funding_gap: [{ peak_amount: gap }],
      natural_hedge_amount: [{ amount: natural }],
      maturity_matched_amount: [{ amount: natural }],
    },
    market_scenario: {
      adverse_rate: adverse,
      band_lower: "1300",
      band_upper: "1400",
      spot_rate: "1350",
      horizon_business_days: 60,
      confidence_level: "0.95",
      volatility_annualized: "0.12",
    },
    hedge_analysis: { optimal_ratio: ratio },
    trade_timeline: Array.from({ length: trades }, (_, index) => ({
      case_id: `TRADE-${index}`,
    })),
    support_candidates: [],
    excluded_candidates: [],
    filing_obligations: [],
    risk_findings: [],
    next_actions: [],
    missing_input_queue: [],
    missing_information: [],
    evidence: [],
    review_required: false,
    review_reasons: [],
    calculation_versions: {},
    workers: { completed: [], failed: {}, skipped: {} },
  };
}

describe("resultChanges", () => {
  it("reports before and after values and ignores unchanged metrics", () => {
    const changes = resultChanges(
      analysis(),
      analysis({ net: "40000", natural: "60000", trades: 2 }),
    );

    expect(changes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          label: "순노출",
          before: "+100,000 USD",
          after: "+40,000 USD",
        }),
        expect.objectContaining({
          label: "자연헤지",
          before: "0 USD",
          after: "60,000 USD",
        }),
        expect.objectContaining({
          label: "분석 거래",
          before: "1건",
          after: "2건",
        }),
      ]),
    );
    expect(changes.some((change) => change.label === "자금 공백")).toBe(false);
  });

  it("states explicitly when recalculation did not change headline values", () => {
    render(<ResultChangeSummary previous={analysis()} result={analysis()} />);
    expect(screen.getByText("주요 계산값은 이전 분석과 같습니다.")).toBeInTheDocument();
  });
});

describe("ResultUpdate", () => {
  it("keeps the repeated full result collapsed until requested", async () => {
    const user = userEvent.setup();
    const result = analysis({ net: "40000" });
    render(
      <ResultUpdate
        previous={analysis()}
        result={result}
        order={[]}
        shown={4}
      />,
    );

    expect(screen.getByLabelText("변경 요약")).toHaveTextContent(
      "순노출+100,000 USD→+40,000 USD",
    );
    const disclosure = screen.getByText("전체 결과 보기").closest("details");
    expect(disclosure).not.toHaveAttribute("open");
    await user.click(screen.getByText("전체 결과 보기"));
    expect(disclosure).toHaveAttribute("open");
  });
});
