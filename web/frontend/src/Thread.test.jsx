import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Thread from "./Thread.jsx";

/** 주장과 근거가 붙어 있는가.
 *
 *  이 화면이 오래 틀렸던 방식은 근거를 빠뜨리는 것이 아니라 근거를 **딴 데**
 *  두는 것이었습니다. 판정 다섯 개가 한 문단으로 이어지고, 그 다섯 개의
 *  근거가 아래 접힘 하나에 전부 들어가 있었습니다. 읽으려면 주장 하나를
 *  외운 뒤 접힘을 열고 해당하는 줄을 찾아 돌아와야 했습니다.
 *
 *  그래서 여기서 확인하는 것은 「근거가 화면에 있는가」가 아니라 「그 근거가
 *  자기 주장 안에 있는가」입니다. 문서 어딘가에 있기만 하면 통과하는 검사는
 *  고치기 전 화면도 통과시킵니다. */
const RESULT = {
  workers: { completed: ["exposure", "support"], skipped: {} },
  cashflow_analysis: { net_exposure: [{ currency: "USD", amount: "100000" }] },
  lead: "pointer",
  pointer: "지원제도 후보 2건 · 정보 부족 1건",
  summary:
    "100,000 USD 결제일까지 미결제 시 최대 10,188,000 KRW 손실 가능합니다. " +
    "K-SURE 일반형 수출 환변동보험은 조건 충족했으나 공식 확인이 필요합니다. " +
    "한국무역보험공사 상담 및 청약 시 6건의 서류가 필요합니다.",
  basis: "거래 순노출 100,000 USD = Σ수취 − Σ지급 · 불리 환율 1,339.22원",
  said: {
    support: [],
    compliance: [],
    actions: [],
    sources: [],
    detail: [],
    grounded: [
      {
        kind: "support",
        claim: "K-SURE 일반형 수출 환변동보험은 조건을 충족합니다.",
        settled: true,
        met: ["국내에 주소를 둔 기업", "중소·중견기업"],
        wanted: [],
      },
      {
        kind: "support",
        claim: "K-SURE 단기수출보험(선적후·개별)은 아직 판정하지 못했습니다.",
        settled: false,
        met: ["수출 거래"],
        wanted: ["국별인수방침 인수제한국 소재가 아님"],
      },
    ],
  },
};

//: `restored`로 둡니다. 살아 있는 턴은 한 조각씩 시계에 맞춰 도착하므로,
//: 검사하려는 것이 배치인데 타이머를 기다리게 됩니다. 복원된 턴은 이미 한 번
//: 읽힌 것이라 통째로 그려지고, 그리는 코드는 같습니다.
const turnsFor = (result) => [
  { who: "agent", kind: "result", result, heard: {}, spoken: true, restored: true },
];

describe("판정과 근거", () => {
  it("각 근거는 자기 주장 안에 있다", () => {
    render(<Thread turns={turnsFor(RESULT)} busy={false} />);

    const [settled, open] = screen.getAllByText(/K-SURE/).map((node) =>
      node.closest(".ground"),
    );

    // 충족한 제도 밑에는 확인한 조건이, 판정보류 밑에는 남은 조건이.
    // 서로의 것이 아니어야 합니다 — 접힘 하나에 다 모여 있던 시절에는 둘 다
    // 「화면에 있음」이었습니다.
    expect(settled).toHaveTextContent("중소·중견기업");
    expect(settled).not.toHaveTextContent("국별인수방침");
    expect(open).toHaveTextContent("국별인수방침 인수제한국 소재가 아님");
    expect(open).not.toHaveTextContent("중소·중견기업");
  });

  it("아직 판정하지 못한 것은 충족한 것과 다르게 표시된다", () => {
    render(<Thread turns={turnsFor(RESULT)} busy={false} />);

    const open = screen
      .getByText(/단기수출보험/)
      .closest(".ground");

    // 「아직 모른다」와 「해당 없다」를 뭉개는 것이 이 화면이 할 수 있는 가장
    // 위험한 일입니다. 하나는 질문이고 하나는 면제입니다.
    expect(open.className).toContain("open");
  });

  it("요약은 한 문장이고, 마지막에 온다", () => {
    render(<Thread turns={turnsFor(RESULT)} busy={false} />);

    const recap = document.querySelector(".recap");

    expect(recap).toHaveTextContent("최대 10,188,000 KRW 손실 가능합니다.");
    // 뒤 문장들은 이미 위 블록이 근거를 달고 말했습니다. 다시 쓰면 같은 답이
    // 두 번이고, 근거 없는 쪽이 앞에 섭니다.
    expect(recap).not.toHaveTextContent("공식 확인이 필요합니다");
    expect(recap).not.toHaveTextContent("6건의 서류");
  });

  it("손실 금액도 근거를 단다", () => {
    render(<Thread turns={turnsFor(RESULT)} busy={false} />);

    // 답변에서 가장 큰 숫자가 유일하게 근거 없이 서 있던 자리입니다.
    expect(document.querySelector(".recap")).toHaveTextContent(
      "Σ수취 − Σ지급",
    );
  });

  it("재작성이 있어도 근거 블록은 그대로 나온다", () => {
    // 재작성은 키가 있을 때만 도는 유일한 경로입니다. 여기서 블록을 끄면
    // 아무도 보고 있는 화면에서만 이 변경이 통째로 사라집니다 — 실제로 한 번
    // 그렇게 냈습니다. 게다가 재작성이 내놓는 것이 바로 이 블록들이 쪼개려던
    // 그 문단입니다: 판정 전부를 하나로 합치고, 어느 것도 자기 근거 옆에
    // 두지 않습니다.
    const retold = {
      ...RESULT,
      said: { ...RESULT.said, retold: "판정 다섯 개를 한 문단으로 합친 문장입니다." },
    };
    render(<Thread turns={turnsFor(retold)} busy={false} />);

    expect(document.querySelectorAll(".ground")).toHaveLength(2);
  });

  it("요약은 금액이 둘째 문장에 와도 금액을 지킨다", () => {
    // 첫 문장에서 자르는 규칙은 이 재작성에서 금액을 통째로 버렸습니다.
    // 계산이 몇 문장을 쓰는지는 모델이 정합니다.
    const late = {
      ...RESULT,
      said: {
        ...RESULT.said,
        retold:
          "100,000 USD 결제가 결제일까지 열려 있습니다. " +
          "환율이 1339.22까지 오르면 10,188,000 KRW 손실입니다. " +
          "K-SURE 일반형 수출 환변동보험은 조건 충족입니다.",
      },
    };
    render(<Thread turns={turnsFor(late)} busy={false} />);

    const recap = document.querySelector(".recap");
    expect(recap).toHaveTextContent("10,188,000 KRW 손실입니다.");
    expect(recap).not.toHaveTextContent("환변동보험");
  });

  it("근거가 없는 옛 응답은 문장이라도 보여준다", () => {
    // 복원된 대화는 그때의 응답을 그대로 들고 옵니다. `grounded`가 없다고
    // 빈 자리를 보여주면, 고치기 전보다 나빠집니다.
    const old = {
      ...RESULT,
      basis: null,
      said: { ...RESULT.said, grounded: undefined, support: ["환변동보험은 조건을 충족합니다."] },
    };
    render(<Thread turns={turnsFor(old)} busy={false} />);

    expect(screen.getByText("환변동보험은 조건을 충족합니다.")).toBeTruthy();
  });
});
