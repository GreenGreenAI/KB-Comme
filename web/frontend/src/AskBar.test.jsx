import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AskBar from "./AskBar.jsx";

const base = {
  pending: null,
  requiredInputs: [],
  onPlace: vi.fn(),
};

describe("AskBar decision input queue", () => {
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
});
