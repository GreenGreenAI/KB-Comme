import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AskBar from "./AskBar.jsx";

/** K-SURE 등급은 A부터 R까지에 「모릅니다」까지 아홉 개입니다. 한 번의
 *  키 입력이면 끝나는 질문이 세로로 200px을 먹고 있었습니다. */
const GRADES = ["A", "B", "C", "D", "E", "F", "G", "R", "모릅니다 · 등급이 없습니다"];

const gradeAsk = {
  field: "company.ksure_exporter_grade",
  question: "K-SURE 수출자 신용등급을 아시나요?",
  opens: "K-SURE 단기수출보험(선적후·개별)",
  options: GRADES.map((label) => ({ value: label, label })),
};

const shortAsk = {
  field: "financing.has_bank_consultation",
  question: "거래 은행과 보증부 대출을 상담해 보셨나요?",
  options: [
    { value: "true", label: "상담했습니다" },
    { value: "false", label: "아직 상담 전입니다" },
  ],
};

const bar = (ask) => (
  <AskBar factInputs={[ask]} onSlot={vi.fn()} onPlace={vi.fn()} />
);

beforeEach(() => {
  // jsdom은 배치를 하지 않아 이 메서드가 없습니다. 있는지 없는지가 아니라
  // 불렸는지가 이 파일이 확인하려는 것입니다.
  Element.prototype.scrollIntoView = vi.fn();
});

describe("고를 것이 많을 때", () => {
  it("긴 목록만 스크롤한다", () => {
    const { rerender } = render(bar(gradeAsk));
    expect(document.querySelector(".choices").className).toContain("scrolls");

    // 두 개짜리 목록에 스크롤 상자를 두르면, 잘린 것이 없는데 잘린 것처럼
    // 보입니다.
    rerender(bar(shortAsk));
    expect(document.querySelector(".choices").className).not.toContain("scrolls");
  });

  it("잘렸다는 것과 몇 개인지를 말한다", () => {
    render(bar(gradeAsk));

    // macOS는 무언가 스크롤되기 전까지 스크롤바를 숨깁니다. 잘린 목록이 짧은
    // 목록처럼 보이면, 「모릅니다」를 본 적 없는 회사가 가지고 있지도 않은
    // 등급을 답합니다.
    expect(screen.getByText(/9개 중 3개/)).toBeTruthy();
  });

  it("짧은 목록에는 그 안내를 붙이지 않는다", () => {
    render(bar(shortAsk));

    expect(screen.queryByText(/개 중 3개/)).toBeNull();
  });

  it("키보드로 내려가면 선택한 줄이 따라 보인다", async () => {
    render(bar(gradeAsk));

    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");

    // 네 번째 줄은 3줄 밖입니다. 캐럿과 음영만이 Enter가 무엇을 고를지
    // 말하고 있는데, 그 줄이 화면 밖이면 아무도 자기가 무엇을 고르는지 볼 수
    // 없습니다.
    expect(document.querySelector("#choice-3").getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("숫자키는 스크롤 밖의 것도 바로 고른다", async () => {
    const onSlot = vi.fn();
    render(<AskBar factInputs={[gradeAsk]} onSlot={onSlot} onPlace={vi.fn()} />);

    await userEvent.keyboard("9");

    // 목록을 자르는 것이 답을 멀게 만들면 안 됩니다. 아홉 번째는 여전히 한
    // 번의 키 입력입니다.
    expect(onSlot).toHaveBeenCalledWith(
      { facts: { "company.ksure_exporter_grade": "모릅니다 · 등급이 없습니다" } },
      "모릅니다 · 등급이 없습니다",
    );
  });
});
