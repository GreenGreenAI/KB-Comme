import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import Notices from "./Notices.jsx";

it("keeps operational failures visible until the user dismisses them", async () => {
  const user = userEvent.setup();
  const onDismiss = vi.fn();
  render(
    <Notices
      notices={[{ id: "session", text: "로그인 상태를 확인하지 못했습니다" }]}
      onDismiss={onDismiss}
    />,
  );

  expect(screen.getByRole("alert")).toHaveTextContent(
    "로그인 상태를 확인하지 못했습니다",
  );
  await user.click(screen.getByRole("button", { name: "닫기" }));
  expect(onDismiss).toHaveBeenCalledWith("session");
});
