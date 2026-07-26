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

`tools`가 참조 가능한 계층은 `domain` 하나뿐이므로(ADR-0003), `HedgeInstrument`와
`InstrumentKind`는 `domain/`에 둔다. Protocol만 `contracts/`에 남는다.

### 3. 제외된 수단도 사유와 함께 반환한다

`HedgeInstrument`는 불변식을 스스로 강제한다.

- `available=False`인데 `exclusion_reasons`가 비면 생성 불가
- `available=True`인데 `exclusion_reasons`가 있으면 생성 불가

§5.4의 "제외 사유를 반드시 반환한다"를 헤지 수단에도 동일하게 적용한 것이다. 후보를
조용히 버리면 사용자는 왜 선물환이 목록에 없는지 알 수 없다.

### 4. 경계 위반은 예외로 중단한다

`assert_all_available`은 이용 불가 수단이 옵티마이저에 도달하면 예외를 던진다.
필터링을 호출자의 규율에 맡기지 않고 코드로 닫는다. `tests/platform/test_hedge_guard.py`가
회귀를 막는다.

## 결과

- `domain/models.HedgeInstrument`, `domain/enums.InstrumentKind` 신설 — 역할 A 승인 필요
- `contracts/interfaces.InstrumentAvailabilityService` 신설 — 역할 A가 구현
- `tools/hedge.py` 신설 (역할 B 소유). §5.3 옵티마이저가 이 위에 올라간다
- 미결: 은행 선물환은 §2.4에서 상품 데이터가 MVP 제외로 확정됐다. `FORWARD`는 열거형에
  남기되, 실제 후보 생성 여부와 `contract_rate` 확보 방법은 역할 A가 §5.4 작업 시 정한다.
