import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DocumentPanel from "./DocumentPanel.jsx";
import {
  checkTradeDocuments,
  confirmDocumentFields,
  listTradeDocuments,
  uploadTradeDocument,
} from "./api.js";

vi.mock("./api.js", () => ({
  checkTradeDocuments: vi.fn(),
  confirmDocumentFields: vi.fn(),
  listTradeDocuments: vi.fn(),
  uploadTradeDocument: vi.fn(),
}));

const trade = {
  case_id: "EXPORT-001",
  amount: "100000",
  currency: "USD",
  expected_payment_date: "2026-10-24",
};

const document = {
  document_id: "DOC-1",
  filename: "invoice.txt",
  document_type: "commercial_invoice",
  extraction_state: "extracted",
  content_hash: "sha256:test",
  extraction: {
    issues: [],
    fields: [
      {
        field_name: "amount",
        normalized_value: "100000",
        confidence: 0.96,
        location: { page: null, line: 5 },
        confirmed: false,
        confirmed_value: null,
      },
    ],
  },
};

describe("DocumentPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listTradeDocuments.mockResolvedValue([]);
    uploadTradeDocument.mockResolvedValue(document);
    confirmDocumentFields.mockResolvedValue({
      ...document,
      extraction: {
        ...document.extraction,
        fields: [
          {
            ...document.extraction.fields[0],
            confirmed: true,
            confirmed_value: "99000",
          },
        ],
      },
    });
    checkTradeDocuments.mockResolvedValue({
      case_id: "EXPORT-001",
      document_count: 1,
      document_types: ["commercial_invoice"],
      review_required: true,
      findings: [
        {
          kind: "trade_document_mismatch",
          field: "amount",
          reason: "확정 거래 정보와 문서 값이 일치하지 않습니다.",
        },
      ],
    });
  });

  it("keeps tenant document upload behind sign-in", () => {
    render(<DocumentPanel trades={[trade]} signedIn={false} />);
    expect(screen.getByText(/로그인 후 업로드/)).toBeInTheDocument();
    expect(screen.queryByLabelText("문서 선택")).not.toBeInTheDocument();
  });

  it("uploads, exposes provenance, confirms fields and reports mismatch", async () => {
    const user = userEvent.setup();
    render(<DocumentPanel trades={[trade]} signedIn />);
    await waitFor(() => expect(listTradeDocuments).toHaveBeenCalledWith("EXPORT-001"));

    const file = new File(["Commercial Invoice"], "invoice.txt", {
      type: "text/plain",
    });
    await user.upload(screen.getByLabelText("문서 선택"), file);
    await user.click(screen.getByRole("button", { name: "업로드·추출" }));

    expect(await screen.findByText("상업송장")).toBeInTheDocument();
    expect(screen.getByText("sha256:test")).toBeInTheDocument();
    const amount = screen.getByLabelText(/금액/);
    await user.clear(amount);
    await user.type(amount, "99000");
    await user.click(screen.getByRole("button", { name: "추출 필드 확인 저장" }));
    await waitFor(() =>
      expect(confirmDocumentFields).toHaveBeenCalledWith(
        "DOC-1",
        expect.objectContaining({ amount: "99000" }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "거래·문서 정합성 검사" }));
    expect(
      await screen.findByText("사람의 확인이 필요한 불일치"),
    ).toBeInTheDocument();
    expect(checkTradeDocuments).toHaveBeenCalledWith(
      "EXPORT-001",
      {
        amount: "100000",
        currency: "USD",
        payment_date: "2026-10-24",
      },
    );
  });
});
