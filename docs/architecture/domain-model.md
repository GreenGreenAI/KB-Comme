---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# 도메인 모델

핵심 모델은 거래(`TradeCase`), 거래 단계, 결제 조건, 통화·금액, 노출과 근거를
중심으로 구성한다.

## 관리 원칙

- 모델은 업무 용어를 사용하고 인프라 타입에 의존하지 않는다.
- 필수값과 불확실한 값을 타입 수준에서 구분한다.
- 외부에 노출된 모델 변경은 공유 계약 변경으로 취급한다.
- 새 필드에는 의미, 단위, 기준일과 누락 시 동작을 기록한다.

## 판정 상태는 boolean으로 표현하지 않는다

자격·가용성 판정은 참·거짓이 아니라 상태다. `DecisionStatus`와
`AvailabilityStatus`는 "불가로 판정됨"과 "판정할 정보가 없음"을 서로 다른 값으로
구분한다. 두 경우를 하나로 합치면 정보 부족이 확정된 거절로 읽히며, 이는 추정하지
않는다는 원칙에 어긋난다. 판정되지 않은 항목은 결과에서 빠지지 않고 검토 대상으로
흐른다.

`CONDITIONALLY_ELIGIBLE`은 이미 알고 있는 보완 가능 조건이 충족되지 않았을 때만
사용한다. `RuleDecision.requirements`에 field, operator, 기대값, 현재값과 설명을
구조화해 보존한다. 입력 사실 자체가 없으면 조건부가 아니라
`INSUFFICIENT_INFORMATION`이다.

## 헤지 수단: 금융상품과 전략

`HedgeMeasure`는 두 범주를 함께 담는다.

| 범주 | 종류 | 가격 필드 |
|---|---|---|
| `FINANCIAL_INSTRUMENT` | 선물환, 환변동보험 | 보장환율·비용률 있음 |
| `STRATEGY` | 자연헤지, 결제조건 조정 | 없음 |

전략에는 계약 상대방이 없으므로 보장환율과 비용률이 성립하지 않으며, 모델이 이를
불변식으로 막는다. 각 수단의 이용 조건(담보 요구 여부 등)은 모델이 아니라 출처가
연결된 규칙에서 표현한다. 모델에 사실을 고정하면 근거 없는 단정이 된다.

## 스냅샷: 관측 시점과 수집 시점

`SnapshotRef`는 `observed_at`(데이터가 서술하는 시점)과 `retrieved_at`(받아온 시점)을
분리한다. 출처가 늦게 고시하거나 캐시된 응답을 주면 둘이 어긋나고, 수집 시점만
검사하면 오래된 데이터가 최신으로 판정된다. 두 시각 모두 시간대를 요구하며 시간대
없는 값은 거부한다.

관련 결정은 [ADR-0003](../adr/0003-snapshot-contract-and-integration-leaf.md),
[ADR-0004](../adr/0004-hedge-instrument-availability-seam.md)에 기록되어 있다.

실제 계약의 단일 진실 공급원은 `src/tradeflow/domain/`과
`src/tradeflow/contracts/`다. 이 문서는 설계 의도와 용어를 설명한다.
