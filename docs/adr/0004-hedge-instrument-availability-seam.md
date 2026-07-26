---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-26
---

# ADR-0004: 헤지 수단 가용성 이음새

- 상태: 제안 (역할 A 승인 대기)
- 날짜: 2026-07-26
- 관련: ADR-0003, MVP 아키텍처 정의서 §4.2[5], §5.3, §5.4, §10

## 배경

정의서 §10은 "담보 없는 기업에 선물환 제시" 위험의 대응을 **"수단 필터링을 도구
레벨에서 강제"** 로 규정한다. §4.2[5]는 필터링 조건을 담보·신용 여력으로 정의한다.

그러나 조건 판정과 손익 계산은 서로 다른 역할의 소유다.

- K-SURE 환변동보험의 이용 조건은 §5.4 자격 판정과 같은 성격 — 역할 A
- 손익 분포와 최적 헤지비율 산출은 §5.3 — 역할 B

두 사람이 같은 판단을 각자 구현하면 서로 다른 답이 나온다.

## 고려한 선택지

| 선택지 | 장점 | 비용 |
|---|---|---|
| 옵티마이저가 담보·신용 fact를 직접 읽어 판정 | 호출이 단순 | `tools`가 자격 판정을 겸하게 되어 §5.4와 판정 로직이 이중화됨 |
| 가용성을 오케스트레이터가 판단해 걸러서 전달 | 계층이 얇아짐 | 정의서 §10이 요구한 "도구 레벨 강제"가 아님. 호출자가 빠뜨리면 그대로 통과 |
| **A가 판정·B가 검증** (채택) | 판정이 한 곳. 경계 위반이 예외로 드러남 | 공유 타입 1개와 Protocol 1개를 유지해야 함 |

## 결정

### 1. 가용성은 지식 계층이 정하고, 옵티마이저는 검증만 한다

| 책임 | 담당 | 위치 |
|---|---|---|
| 가용성 판정 | 역할 A | `contracts.InstrumentAvailabilityService` Protocol, `knowledge/` 구현 |
| payoff 계산 | 역할 B | `tools/` (§5.3 옵티마이저) |
| 경계 강제 | 역할 B | `tools/hedge.py` |

옵티마이저는 `available=True`인 수단만 손익식에 넣는다. 가용성을 스스로 판단하지
않으며, 판단하려 해도 담보·신용 fact에 접근할 경로가 없다.

### 2. 데이터 타입은 `domain/`에 둔다

`tools`가 참조 가능한 계층은 `domain` 하나뿐이므로(ADR-0003), `HedgeMeasure`와 관련
열거형은 `domain/`에 둔다. Protocol만 `contracts/`에 남는다.

### 3. 가용성은 boolean이 아니라 상태다

`AvailabilityStatus`는 `AVAILABLE` / `UNAVAILABLE` / `CONDITIONAL` /
`INSUFFICIENT_INFORMATION` / `EXPERT_CONFIRMATION_REQUIRED`를 갖는다. `DecisionStatus`와
같은 구조다.

boolean은 **"이용 불가로 판정됨"과 "판정할 정보가 없음"을 같은 값으로 만든다.** 정보
부족이 확정된 거절로 읽히는 것은 이 제품이 금지하는 추론이다(§4.5, §9.2). 판정되지
않은 수단은 손익 비교가 아니라 `review_required`로 흐른다.

### 4. 금융상품과 전략을 분리한다

`FinancialInstrumentKind`(선물환, 환변동보험)와 `HedgeStrategyKind`(자연헤지, 결제조건
조정)를 나누고 `HedgeMeasureCategory`로 구분한다.

전략에는 계약 상대방이 없으므로 보장환율과 비용률이 성립하지 않는다. 불변식으로
강제해 전략에 가격 필드가 붙는 것을 생성 시점에 막는다.

**담보 관련 사실은 열거형에 적지 않는다.** 이전 판은 "선물환 = 담보 필요", "환변동보험
= 담보 불요"를 주석으로 고정했으나, 공식 source ID가 연결되지 않은 상태에서 이는 근거
없는 단정이다. 이 사실들은 역할 A의 룰팩에서 출처와 함께 표현된다.

### 5. 제외된 수단도 사유와 함께 반환한다

`HedgeMeasure`는 불변식을 스스로 강제한다.

- `AVAILABLE`이 아닌데 `status_reasons`가 비면 생성 불가
- `AVAILABLE`인데 `status_reasons`가 있으면 생성 불가

§5.4의 "제외 사유를 반드시 반환한다"를 헤지 수단에도 동일하게 적용한 것이다. 후보를
조용히 버리면 사용자는 왜 선물환이 목록에 없는지 알 수 없다.

### 6. 경계 위반은 예외로 중단한다

`assert_all_usable`은 `AVAILABLE`이 아닌 수단이 옵티마이저에 도달하면 예외를 던진다.
필터링을 호출자의 규율에 맡기지 않고 코드로 닫는다.

## 결과

- `domain/models.HedgeMeasure`, `domain/enums`의 `AvailabilityStatus` ·
  `HedgeMeasureCategory` · `FinancialInstrumentKind` · `HedgeStrategyKind` 신설 —
  역할 A 승인 필요
- `contracts/interfaces.HedgeMeasureAvailabilityService` 신설 — 역할 A가 구현
- `tools/hedge.py` 신설 (역할 B 소유). §5.3 옵티마이저가 이 위에 올라간다
- 미결: 은행 선물환은 §2.4에서 상품 데이터가 MVP 제외로 확정됐다. `FORWARD`는 열거형에
  남기되, 실제 후보 생성 여부와 `contract_rate` 확보 방법은 역할 A가 §5.4 작업 시 정한다.
- 미결: `CONDITIONAL`의 조건 표현 방식(자유 문장 대 구조화 조건)은 역할 A가 §5.4에서
  정한다. 현재는 `status_reasons` 문자열로만 전달한다.

## 검증

- `tests/platform/test_hedge_guard.py`가 `AVAILABLE`이 아닌 수단이 손익 계산 후보에서
  빠지는지, 판정되지 않은 수단이 이용 불가와 구분되어 검토로 흐르는지, 사유가 응답용으로
  보존되는지 검사한다.
- 같은 파일이 `AVAILABLE`이 아닌 수단을 경계에 넣으면 `UnusableMeasureError`가 발생하는지
  검사한다.
- `HedgeMeasure`의 불변식(사유 없는 비가용 불가, 사유 있는 가용 불가, 범주·종류 불일치
  불가, 전략의 가격 필드 불가, 음수 비용률 불가)은 생성 시점에 검사된다.

**현재 상태는 "강제 장치 준비"이지 "도구 수준 강제 완료"가 아니다.** §5.3 옵티마이저가
아직 없어 `assert_all_usable`이 실행 경로에 연결되어 있지 않다. 정의서 §10의 요구가
충족되는 시점은 옵티마이저 진입부에서 이 함수가 호출되고, 그 호출을 검사하는 테스트가
추가될 때다. 이는 역할 B의 Sprint 2 작업이다.
