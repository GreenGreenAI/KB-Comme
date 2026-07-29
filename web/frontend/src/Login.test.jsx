import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Login from "./Login.jsx";
import { signIn } from "./api.js";

vi.mock("./api.js", () => ({ signIn: vi.fn() }));

describe("Login", () => {
  beforeEach(() => {
    signIn.mockReset();
  });

  it("authenticates through the API and returns the server account", async () => {
    const user = userEvent.setup();
    const onSignIn = vi.fn();
    const account = {
      account_id: "COMPANY-HANBIT",
      company_name: "한빛정밀",
    };
    signIn.mockResolvedValue(account);
    render(<Login onSignIn={onSignIn} />);

    await user.type(screen.getByLabelText("이메일"), "kim@hanbit.co.kr");
    await user.type(screen.getByLabelText("비밀번호"), "tradeflow-demo");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(signIn).toHaveBeenCalledWith(
      "kim@hanbit.co.kr",
      "tradeflow-demo",
    );
    expect(onSignIn).toHaveBeenCalledWith(account);
  });

  it("shows authentication failures beside the form", async () => {
    const user = userEvent.setup();
    signIn.mockRejectedValue(new Error("이메일 또는 비밀번호가 올바르지 않습니다"));
    render(<Login onSignIn={vi.fn()} />);

    await user.type(screen.getByLabelText("이메일"), "wrong@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "wrong");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "이메일 또는 비밀번호가 올바르지 않습니다",
    );
    expect(screen.getByRole("button", { name: "로그인" })).toBeEnabled();
  });

  it("does not promise analysis persistence that is not implemented", () => {
    render(<Login onSignIn={vi.fn()} />);

    expect(screen.queryByText(/거래 내역과 산출 근거 보관/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/기업 정보를 반복해서 입력하지 않아도/),
    ).toBeInTheDocument();
  });
});
