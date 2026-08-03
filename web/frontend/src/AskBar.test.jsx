import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AskBar from "./AskBar.jsx";

const base = {
  pending: null,
  requiredInputs: [],
  missingInputs: [],
  quoteInputs: [],
  onPlace: vi.fn(),
  onSplit: vi.fn(),
};

describe("AskBar decision input queue", () => {
  it("sends the decisive liquidity answer as an opening balance", async () => {
    const user = userEvent.setup();
    const onSlot = vi.fn();
    render(
      <AskBar
        {...base}
        decisiveQuestions={[{
          question_id: "liquidity.opening_balance.USD",
          field: "opening_balance_usd",
          scope: "liquidity",
          question: "현재 보유한 USD 외화잔액은 얼마인가요?",
        }]}
        onSlot={onSlot}
        onUnknown={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("opening_balance_usd"), "20000");
    await user.click(screen.getByRole("button", { name: "확인" }));
    expect(onSlot).toHaveBeenCalledWith(
      { profile: { opening_balance_usd: "20000" } },
      "20000",
    );
  });

  it("keeps an unknown answer unknown instead of sending false", async () => {
    const user = userEvent.setup();
    const onSlot = vi.fn();
    const onUnknown = vi.fn();
    render(
      <AskBar
        {...base}
        missingInputs={[{
          field: "company.credit_issue_free",
          scope: "profile",
          subject_id: "EXPORT-001",
        }]}
        onSlot={onSlot}
        onUnknown={onUnknown}
      />,
    );

    await user.click(screen.getByRole("button", { name: "모름 · 추정하지 않음" }));
    expect(onUnknown).toHaveBeenCalledWith("company.credit_issue_free");
    expect(onSlot).not.toHaveBeenCalled();
  });

  it("sends a compliance answer to the declaration contract", async () => {
    const user = userEvent.setup();
    const onSlot = vi.fn();
    render(
      <AskBar
        {...base}
        missingInputs={[{
          field: "payment.is_netting",
          scope: "compliance_declaration",
          subject_id: "EXPORT-002",
        }]}
        onSlot={onSlot}
        onUnknown={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("option", { name: /예/ }));
    expect(onSlot).toHaveBeenCalledWith(
      { declaration: { case_index: 1, is_netting: true } },
      "예",
    );
  });

  it("sends profile facts under company_facts", async () => {
    const user = userEvent.setup();
    const onSlot = vi.fn();
    render(
      <AskBar
        {...base}
        missingInputs={[{
          field: "company.size",
          scope: "profile",
          subject_id: "EXPORT-001",
        }]}
        onSlot={onSlot}
        onUnknown={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("option", { name: /중소기업/ }));
    expect(onSlot).toHaveBeenCalledWith(
      { profile: { company_facts: { "company.size": "small" } } },
      "중소기업",
    );
  });

  it("confirms a mixed sentence as two structured trades", async () => {
    const user = userEvent.setup();
    const onSplit = vi.fn();
    const candidates = [
      { direction: "수입", amount: "60000", expected_payment_date: "2026-08-25" },
      { direction: "수출", amount: "100000", expected_payment_date: "2026-10-24" },
    ];
    render(
      <AskBar
        {...base}
        pending={{
          status: "needs_trade_split",
          question: "두 거래로 나누어 계산할까요?",
          candidates,
        }}
        onSplit={onSplit}
        onSlot={vi.fn()}
        onUnknown={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("option", { name: /2건의 거래/ }));
    expect(onSplit).toHaveBeenCalledWith(candidates);
  });

  it("sends bank consultation to the case named by the packet", async () => {
    const user = userEvent.setup();
    const onSlot = vi.fn();
    render(
      <AskBar
        {...base}
        missingInputs={[{
          field: "financing.has_bank_consultation",
          scope: "case",
          subject_id: "EXPORT-002",
        }]}
        onSlot={onSlot}
        onUnknown={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("option", { name: /예/ }));
    expect(onSlot).toHaveBeenCalledWith(
      {
        caseIndex: 1,
        case: {
          case_facts: { "financing.has_bank_consultation": true },
        },
      },
      "예",
    );
  });
});
