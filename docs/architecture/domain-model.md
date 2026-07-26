---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-26
---

# 도메인 모델

핵심 모델은 거래(`TradeCase`), 거래 단계, 결제 조건, 통화·금액, 노출과 근거를
중심으로 구성한다.

## 관리 원칙

- 모델은 업무 용어를 사용하고 인프라 타입에 의존하지 않는다.
- 필수값과 불확실한 값을 타입 수준에서 구분한다.
- 외부에 노출된 모델 변경은 공유 계약 변경으로 취급한다.
- 새 필드에는 의미, 단위, 기준일과 누락 시 동작을 기록한다.

실제 계약의 단일 진실 공급원은 `src/tradeflow/domain/`과
`src/tradeflow/contracts/`다. 이 문서는 설계 의도와 용어를 설명한다.
