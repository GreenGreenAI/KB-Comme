import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Nav from "./Nav.jsx";

/** 「새 대화」는 자기 작업을 지우는 버튼이라, 있을 때만 있고 누르면 바로
 *  동작합니다. 확인 대화상자는 두지 않았습니다 — 잃는 것은 한 문장이면 다시
 *  칠 수 있는 대화이고, 시연 중에 사이에 끼는 창이 막는 실수보다 비쌉니다. */
describe("새 대화", () => {
  it("지울 대화가 있을 때만 보인다", () => {
    const { rerender } = render(<Nav signInOpen={false} onStartOver={null} />);

    expect(screen.queryByRole("button", { name: "새 대화" })).toBeNull();

    rerender(<Nav signInOpen={false} onStartOver={() => {}} />);

    expect(screen.getByRole("button", { name: "새 대화" })).toBeTruthy();
  });

  it("누르면 한 번에 시작한다", async () => {
    const startOver = vi.fn();
    render(<Nav signInOpen={false} onStartOver={startOver} />);

    await userEvent.click(screen.getByRole("button", { name: "새 대화" }));

    expect(startOver).toHaveBeenCalledTimes(1);
  });

  it("브랜드와 다른 버튼이다", async () => {
    // 하나는 처음 화면으로 가고 대화는 그대로 둡니다. 같은 컨트롤에 두 의도를
    // 얹으면 어느 쪽이 일어날지 누르기 전에 알 수 없습니다.
    const onHome = vi.fn();
    const startOver = vi.fn();
    render(<Nav signInOpen={false} onHome={onHome} onStartOver={startOver} />);

    await userEvent.click(screen.getByRole("button", { name: /TradeFlow/ }));

    expect(onHome).toHaveBeenCalledTimes(1);
    expect(startOver).not.toHaveBeenCalled();
  });
});
