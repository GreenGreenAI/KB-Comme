---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-28
---

# TradeFlow의 이론적·개념적 기반

## 1. 목적

이 문서는 TradeFlow가 어떤 이론과 설계 개념을 바탕으로 만들어졌는지, 그 개념이
제품 안에서 어떤 책임을 갖는지, 현재 어느 수준까지 구현됐는지를 한곳에 정리한다.
대상 독자는 제품 담당자, 도메인 전문가, 모델 검증자와 개발자다.

이 문서는 개별 법규의 해석서나 모델 사용설명서를 대신하지 않는다. 실제 운영
파라미터와 모델 상태는
[`hedge_model_registry.json`](../../knowledge/hedge_model_registry.json), 규정 근거는
[`source_registry.json`](../../knowledge/source_registry.json), 실행 계약은
[`contracts.md`](../specifications/contracts.md)를 각각 단일 진실 공급원으로 삼는다.

### 1.1 상태 표기

| 상태 | 의미 |
|---|---|
| **구현** | 현재 코드와 테스트에서 실행되는 개념 |
| **거버넌스** | 정책·계약·승격 조건은 존재하지만 운영 승인이 별도로 필요한 개념 |
| **데이터 대기** | 알고리즘은 있으나 정당한 운영 데이터가 없어 사용할 수 없는 개념 |
| **설계** | 제품 방향에는 포함되지만 현재 실행 경로가 완성되지 않은 개념 |
| **미적용** | TradeFlow가 현재 사용한다고 주장해서는 안 되는 개념 |

## 2. 전체 의사결정 원리

TradeFlow는 다음 흐름을 따른다.

```text
검증된 사실
  → 결정론적 계산
  → 선언적 규칙 판정
  → 불확실성·근거·검토 상태 부여
  → DecisionPacket 고정
  → LLM의 설명과 누락 정보 질문
  → 사람의 확인과 실제 실행
```

핵심 원칙은 **LLM이 계산기, 법규 판정기 또는 금융상품 실행기가 되지 않게 하는
것**이다. 수치와 규정 상태는 테스트 가능한 코드가 만들고, LLM은 구조화된 결과를
사용자가 이해하고 행동할 수 있는 언어로 바꾼다.

이 원칙은
[ADR-0007](../adr/0007-llm-execution-boundary-and-decision-packet.md)과
[ADR-0025](../adr/0025-hedge-model-champion-challenger-governance.md)에 구체화돼 있다.

## 3. 기업 외환위험과 현금흐름

### 3.1 거래적 외환노출

기업이 외화로 받을 금액 또는 지급할 금액은 계약일부터 결제일까지 원화 가치가
변한다. TradeFlow는 회계 환산노출이나 장기 경제적 노출 전체가 아니라, 우선
수출입 계약에서 발생하는 **거래적 외환노출(transaction exposure)**을 대상으로
한다.

통화 `c`, 시점 `t`의 단순 거래 순노출은 다음과 같이 볼 수 있다.

```text
trade_net_exposure(c, t)
  = Σ 외화 유입(c, t) - Σ 외화 유출(c, t)
```

현재 구현에서는 양의 노출은 외화 순유입, 음의 노출은 외화 순유출을 뜻한다. 이
부호 규칙은 이후 환손익과 헤지 방향을 결정하므로 LLM이 해석해서 바꿀 수 없다.

**적용 상태: 구현**

- `TradeProgram`이 기업 프로필, 거래, 기초 외화잔액과 입력 스냅샷을 묶는다.
- `TradeCase`가 통화, 금액, 수출입 방향, 결제일과 거래 속성을 표현한다.
- 통화별 유입, 유출, 순노출과 잔액 경로를 계산한다.

관련 문서: [도메인 모델](domain-model.md),
[MVP 아키텍처 §5.1](../specifications/mvp-architecture.md)

### 3.2 자연헤지와 만기 대응

**자연헤지(natural hedge)**는 같은 통화의 반대 방향 현금흐름을 파생상품 없이
상계하는 방식이다.

```text
economic_offset(c) = min(총 유입(c), 총 유출(c))
```

그러나 총액이 같더라도 지급일보다 수취일이 늦으면 중간 자금 부족은 사라지지
않는다. 따라서 TradeFlow는 다음을 구분한다.

- `natural_hedge_amount`: 분석 기간 전체의 경제적 상계 가능액
- `maturity_matched_amount`: 허용된 만기 구간 안에서 실제 대응되는 금액
- `trade_net_exposure`: 거래 전체 상계 후 남은 방향성 노출
- `funding_gap`: 시점별 잔액이 음수가 되는 구간

이 구분은 “순노출은 작지만 결제일까지 운전자금이 부족한” 상황을 감추지 않기
위한 것이다.

**적용 상태: 구현**

### 3.3 유동성 위험

외화 기초잔액과 날짜별 현금흐름을 누적해 잔액 경로를 만들고, 가장 큰 음수 잔액을
최대 자금 부족으로 본다.

```text
balance(c, t)
  = opening_balance(c) + Σ cashflow(c, τ),  τ ≤ t

funding_gap(c)
  = max(0, -min_t balance(c, t))
```

이는 시장위험과 유동성 위험을 구분한다. 환율 위험을 충분히 헤지했더라도 실제
지급 시점의 외화가 부족할 수 있다.

**적용 상태: 구현**

## 4. 환율 수익률과 시장 시나리오

### 4.1 로그수익률

환율 수준 `S_t`에서 일별 로그수익률은 다음과 같다.

```text
r_t = ln(S_t / S_(t-1))
```

로그수익률은 여러 기간의 수익률을 합산할 수 있고 양의 가격 과정과 자연스럽게
연결되므로 변동성 추정과 역사적 시나리오의 공통 입력으로 사용한다.

**적용 상태: 구현**

### 4.2 표본변동성, 이동창과 기간 환산

기준 모델은 최근 `N`개 관측치의 표본표준편차로 일별 변동성을 구하고, 결제까지
`T`영업일 변동성을 제곱근 시간 법칙으로 환산한다.

```text
σ_daily = sample_stdev(r_(t-N+1), …, r_t)
σ_T     = σ_daily × sqrt(T)
```

제곱근 시간 법칙은 수익률이 독립적이고 분산이 안정적이라는 단순화에 기대므로,
시장 급변과 변동성 군집을 완전히 표현하지 않는다. 따라서 TradeFlow는 이를
투명한 기준 모델로 두고 EWMA와 GARCH 계열을 challenger로 비교한다.

**적용 상태: 구현**

### 4.3 무표류 로그정규 시나리오

기준 모델은 환율 방향을 맞히려 하지 않고 표류항을 0으로 고정한다.

```text
S_scenario = S_0 × exp(z_q × σ_T)
```

수출기업과 수입기업에 불리한 환율 방향이 반대이므로 노출 부호에 따라 adverse
분위수를 선택한다. 이 값은 확정 환율 예측이 아니라, 현재 변동성 가정 아래의
조건부 스트레스 시나리오다.

**적용 상태: 구현**

### 4.4 Historical Simulation

Historical Simulation은 정규분포를 가정하지 않고 과거에 실현된 중첩 기간
수익률의 경험분포를 사용한다. 실제 꼬리와 비대칭을 일부 보존할 수 있지만, 과거에
없던 충격을 만들지 못하고 관측창 선택에 민감하다.

**적용 상태: 구현, challenger**

참고: [Basel Committee의 시장위험 문서](https://www.bis.org/bcbs/publ/d457.htm)

### 4.5 EWMA 변동성

EWMA(Exponentially Weighted Moving Average)는 최근 충격에 더 큰 가중치를 준다.

```text
σ_t² = λσ_(t-1)² + (1-λ)r_(t-1)²
```

현재 기본 감쇠계수는 `λ = 0.94`다. 이동창 표준편차보다 최근 급변에 빠르게
반응하지만, 단일 감쇠계수를 지속적으로 검증해야 한다.

**적용 상태: 구현, challenger**

참고: [RiskMetrics Technical Document](https://www.msci.com/documents/10199/5915b101-4206-4ba0-aee2-3449d5c7e95a)

### 4.6 GARCH(1,1)와 Filtered Historical Simulation

GARCH(1,1)는 변동성이 큰 시기와 작은 시기가 군집하는 현상을 다음과 같이
모델링한다.

```text
σ_t² = ω + αε_(t-1)² + βσ_(t-1)²
```

TradeFlow의 GARCH-FHS는 추정한 조건부 변동성으로 잔차를 표준화하고, 그 경험적
잔차를 다시 사용해 시나리오를 만든다. 현재 구현은 결정론적 grid QMLE와 경험적
표준화 잔차를 사용하며 **Student-t 혁신분포를 사용하지 않는다**.

**적용 상태: 구현, challenger**

참고: [Bollerslev, Generalized Autoregressive Conditional Heteroskedasticity](https://doi.org/10.1016/0304-4076(86)90063-1)

### 4.7 분위수, VaR 유사 해석과 Expected Shortfall

분위수는 정해진 신뢰수준에서 손실 경계를 제시한다. 다만 TradeFlow의 adverse
rate는 기업 현금흐름 시나리오를 위한 내부 위험측정치이며, 규제 자본 VaR라고
주장하지 않는다.

Expected Shortfall(ES, CVaR)은 분위수 경계를 넘어선 손실의 평균을 측정한다.

```text
ES_q = E[L | L ≥ VaR_q]
```

Historical CVaR 모델은 후보 헤지비율별 꼬리 손실을 비교하고, 꼬리 손실이 가장
작은 비율 중 더 작은 헤지비율을 선택한다.

**적용 상태: 구현, challenger**

참고:
[Rockafellar·Uryasev, Optimization of Conditional Value-at-Risk](https://doi.org/10.21314/JOR.2000.038)

## 5. 헤지 의사결정

### 5.1 선형 선물환 손익

현재 MVP는 선물환의 만기 손익을 환율에 대해 선형으로 본다. 노출 `E`, 헤지비율
`h`, 현물 시나리오 `S`, 계약환율 `F`, 비용률 `c`가 있을 때 분석은 헤지하지 않은
노출, 선물환 payoff와 비용을 결합한다.

핵심 제약은 다음과 같다.

- `0 ≤ h ≤ 1`: 노출액을 넘는 과잉헤지 금지
- 실제 사용할 수 있는 `HedgeMeasure`와 계약환율 필요
- 공개 현물환율이나 합성 이론 선물환율을 실제 고객 견적으로 간주하지 않음
- `h = 1`이어도 목표를 달성하지 못하면 임의 값을 추천하지 않음

**적용 상태: 구현**

관련 결정:
[ADR-0004](../adr/0004-hedge-instrument-availability-seam.md),
[ADR-0024](../adr/0024-user-confirmed-forward-quote-availability.md)

### 5.2 손익분기 환율과 profit floor

손익분기 환율은 기준 이익과 순노출을 사용해 영업이익이 0이 되는 환율을
계산한다. Profit-floor hedge는 불리한 시나리오에서도 사용자가 정한 최소 영업이익
`Π_floor`를 지키는 가장 작은 헤지비율을 찾는다.

```text
minimize h
subject to Π(S_adverse, h) ≥ Π_floor
           0 ≤ h ≤ 1
```

이는 “위험을 가장 많이 줄이는 비율”이 아니라 “명시된 이익 제약을 충족하는 최소
개입”이라는 제약 최적화다. 목표 이익, 비용과 실제 계약 조건이 바뀌면 권장 비율도
달라진다.

**적용 상태: 구현, 현재 champion**

### 5.3 최소분산 헤지비율

현물수익률 `ΔS`와 선물환수익률 `ΔF`가 쌍으로 관측될 때 전통적인 최소분산
헤지비율은 다음과 같다.

```text
h* = Cov(ΔS, ΔF) / Var(ΔF)
```

TradeFlow에는 계산 함수가 있지만 기업이 실제로 사용할 수 있었던 과거 선물환
호가가 없다. 현물환율, KRX 표준화 선물 또는 금리평가로 만든 합성 선물환은
회사별 OTC 선물환 조건을 대신하지 못한다.

**적용 상태: 데이터 대기**

참고: [Ederington, The Hedging Performance of the New Futures Markets](https://doi.org/10.1111/j.1540-6261.1979.tb02077.x)

필요 데이터:
[선물환 호가 이력 명세](../specifications/forward-quote-history-data.md)

## 6. 모델 검증과 모델위험 관리

### 6.1 Champion–Challenger

운영 모델을 자동으로 최신 또는 가장 복잡한 모델로 바꾸지 않는다.

- champion: `rolling_normal_profit_floor`
- challengers: Historical Simulation, EWMA, GARCH-FHS, Historical CVaR
- data blocked: Minimum Variance Forward

모든 모델은 같은 관측 시점과 같은 경제적 입력으로 비교한다. 모델이 실패했을 때
다른 모델로 조용히 교체하면 어떤 방법으로 결론이 났는지 알 수 없으므로
`automatic_challenger_fallback=false`를 유지한다.

**적용 상태: 구현 + 거버넌스**

### 6.2 Walk-forward와 no-lookahead

평가 원점 `t`와 예측기간 `h`에 대해:

1. `t`까지 이용 가능했던 데이터만 모델에 제공한다.
2. `t`에 관측된 계약 조건으로 헤지비율을 고정한다.
3. `t+h` 데이터는 고정된 결정을 채점할 때만 사용한다.
4. 원점을 앞으로 이동해 같은 과정을 반복한다.

이 방식은 미래 정보 누출을 막고 실제 의사결정 환경을 모사한다.

**적용 상태: 구현**

### 6.3 평가 지표

| 지표 | 답하는 질문 |
|---|---|
| adverse-quantile breach rate | 불리한 경계를 실제로 얼마나 자주 넘었는가 |
| calibration error | 명목 신뢰수준과 실제 초과율이 얼마나 다른가 |
| profit-floor breach rate | 목표 최소이익을 지키지 못한 빈도는 얼마인가 |
| mean/max/tail shortfall | 위반 시 손실의 평균·최대·꼬리는 얼마인가 |
| Expected Shortfall | 극단 손실 평균이 기준 모델보다 줄었는가 |
| quantile loss | 분위수의 위치와 위반을 함께 평가하면 개선됐는가 |
| estimated cost | 개선을 위해 헤지 비용이 얼마나 증가했는가 |
| ratio turnover | 헤지비율이 지나치게 자주 바뀌는가 |
| stress-period metrics | 급변기에도 개선이 유지되는가 |
| failure count | 모델 실패를 성능지표 밖으로 숨기지 않았는가 |

현재 명시적 `overhedge frequency`와 영속 백테스트 결과 저장소는 별도 지표·시설로
완성되지 않았다. 과잉헤지는 실행 비율 범위 제약으로 차단한다.

### 6.4 승격 게이트

challenger 승격은 가중 평균 점수가 아니라 모든 안전 게이트를 통과해야 한다.
현재 기본 게이트는 다음과 같다.

- 평가 원점 100개 이상
- 모델 실패 0회
- calibration error 0.03 이하
- ES 2% 이상 개선
- quantile loss 1% 이상 개선
- profit-floor 위반률 악화 없음
- 비용 증가 10% 이하
- turnover 증가 0.05 이하
- 관측된 회사 적용 가능 선물환 호가 사용
- knowledge-domain, platform-runtime, domain expert의 3자 승인

**적용 상태: 거버넌스. 실제 승격은 선물환 데이터와 승인 전까지 금지**

상세 명세:
[헤지 모델 검증](../specifications/hedge-model-validation.md)

## 7. 규정 및 지원제도 판정

### 7.1 선언적 규칙 기반 전문가 시스템

금액 임계값, 거래 방향, 결제구조, 기업 속성과 유효기간처럼 명시할 수 있는 조건은
LLM 프롬프트가 아니라 버전이 있는 rulepack으로 표현한다. 코드와 데이터의 경계를
두면 규정 개정 시 판정 엔진을 다시 작성하지 않고 규칙과 검증 사례를 함께 바꿀
수 있다.

**적용 상태: 구현**

적용 영역에는 K-SURE 상품 후보 판정, 상계·다자간 상계, 제3자 지급, 선급·선수,
비은행 결제와 상호계정 관련 외환 컴플라이언스 게이트가 포함된다.

### 7.2 열린 세계 가정과 3값 논리

현실의 기업 데이터에서는 필요한 사실이 빠질 수 있다. 따라서 TradeFlow는
“정보가 없음”을 “조건이 거짓”과 동일하게 처리하지 않는다.

```text
TRUE     : 조건을 충족한다는 근거가 있음
FALSE    : 조건을 충족하지 않는다는 근거가 있음
UNKNOWN  : 판정에 필요한 근거가 없음
```

이 열린 세계 가정(open-world assumption)은 누락 정보 때문에 지원 대상에서
잘못 제외하거나 신고 검토를 잘못 면제하는 것을 막는다.

**적용 상태: 구현**

### 7.3 Fail-closed와 후보 판정

출처가 만료됐거나 핵심 사실이 없거나 상충하는 경우 자동 확정으로 진행하지 않는다.
대신 `INSUFFICIENT_INFORMATION`, `SOURCE_EXPIRED`,
`EXPERT_CONFIRMATION_REQUIRED` 같은 상태와 누락 정보를 반환한다.

지원제도 결과도 확정 자격이나 법률의견이 아니라 신청 가능성을 좁히는
**candidate**다. 실제 계약, 신고와 신청은 담당자 또는 전문가의 확인을 거친다.

**적용 상태: 구현**

### 7.4 시간 규칙과 경계값

규정은 시행일·폐지일·공고기간을 갖고, “3개월”은 고정 90일과 다를 수 있다.
TradeFlow는 유효기간을 판정 기준일과 비교하고, 달력 월 규칙과 말일 보정을
결정론적으로 계산한다.

금액·기간·비율 임계값은 바로 아래, 동일, 바로 위의 사례를 validation suite로
검증한다. 대표 사례는 golden case로 보존해 규칙 개정의 회귀를 찾는다.

**적용 상태: 구현**

### 7.5 근거 결합

판정에 사용되는 사실은 값만 전달하지 않고 대상 case, source ID, 문서 버전,
효력기간과 함께 전달한다. 규칙 결과에서 최종 `DecisionPacket`까지 근거를
손실하지 않는 것이 목표다.

**적용 상태: 구현**

관련 결정:
[ADR-0006](../adr/0006-source-status-and-conditional-decisions.md),
[ADR-0008](../adr/0008-evidence-bound-case-facts.md),
[ADR-0019](../adr/0019-rulepack-promotion-and-review-policy.md)

## 8. 데이터 공학과 재현성

### 8.1 Point-in-time와 immutable snapshot

의사결정은 현재 최신 데이터가 아니라 **그 의사결정 시점에 이용할 수 있었던
데이터**로 재현돼야 한다. 각 snapshot은 다음 정보를 갖는다.

- source ID와 원문 위치
- source가 관측한 시점
- 시스템이 수집한 시점
- 데이터 버전과 스키마
- 효력 시작일·종료일
- content hash

원본 snapshot은 수정하지 않고 새 버전을 추가한다. 과거 결과를 다시 실행할 때
원래 hash와 버전을 선택함으로써 사후 개정된 규정이나 데이터가 과거 판단에
섞이는 것을 막는다.

**적용 상태: 구현**

### 8.2 데이터 계보와 원본·정규화 분리

```text
official source/API
  → raw immutable snapshot
  → parser
  → normalized domain object
  → fact/calculation
  → rule/model result
  → DecisionPacket
```

raw 데이터는 증거와 재파싱을 위해 보존하고, normalized 객체는 계산을 위한
일관된 타입을 제공한다. 각 변환 단계의 출처와 버전을 유지해 최종 숫자나 판정이
어디에서 왔는지 추적한다.

**적용 상태: 구현**

### 8.3 Registry와 Ports and Adapters

dataset registry는 데이터셋의 식별자, 스키마, freshness 정책과 parser를 선언한다.
adapter registry는 ECOS, 기업마당, K-SURE, ERP 등 외부 공급자의 I/O를 도메인과
분리한다.

이 구조는 공급자가 바뀌어도 핵심 계산과 규칙이 특정 API 응답 형식에 종속되지
않도록 한다.

**적용 상태: 구현**

관련 결정:
[ADR-0011](../adr/0011-declarative-dataset-and-adapter-registries.md),
[ADR-0014](../adr/0014-deterministic-collection-orchestration.md)

### 8.4 정확한 금액 표현

금액, 환율과 비용률은 가능한 한 `Decimal`과 문자열 직렬화를 사용한다.
이진 부동소수점의 표현 오차가 금융 금액, 경계값 판정과 hash 재현성에 영향을
주는 것을 피하기 위한 선택이다.

**적용 상태: 구현**

### 8.5 공공 벤치마크와 기업 적용 데이터

공공 환율과 시장 데이터는 변동성·진단·benchmark에 사용할 수 있다. 반면
고객별 한도, spread, 유효시간과 은행 조건이 포함된 선물환 호가는 기업별
민감 증거다. 두 종류를 같은 데이터로 취급하지 않는다.

**적용 상태: 구현 원칙 + 선물환 이력은 데이터 대기**

## 9. 소프트웨어 아키텍처

### 9.1 Domain-Driven Design

수출입 거래를 단순 채팅 메시지가 아니라 `TradeProgram` aggregate와 불변에 가까운
value object로 모델링한다. 핵심 불변조건은 도메인 계층에 두고 UI나 API 형식과
분리한다.

**적용 상태: 구현**

### 9.2 Hexagonal Architecture와 의존성 역전

TradeFlow는 domain, contracts, knowledge, tools, runtime, agent, integration을
분리한다.

- domain: 기업·거래·노출의 의미와 불변조건
- contracts: 계층 간 공유하는 버전 계약
- knowledge: 규칙, 근거, 모델 정책
- tools: 순수 계산과 검증
- runtime: 결정론적 파이프라인 조립
- agent: 입력 보완, 경로 선택과 설명
- integration: 외부 API·파일·저장소 I/O

핵심 계층은 외부 공급자의 구체 구현 대신 Protocol과 contract에 의존한다.
integration은 I/O leaf로 남아 계산과 규칙을 오염시키지 않는다.

**적용 상태: 구현**

관련 결정:
[ADR-0001](../adr/0001-module-ownership-and-dependencies.md),
[ADR-0003](../adr/0003-snapshot-contract-and-integration-leaf.md)

### 9.3 Functional Core / Imperative Shell

환노출, 변동성, 헤지와 규칙 판정은 동일 입력에 동일 결과를 내는 결정론적 core로
유지한다. 네트워크 호출, 저장과 시각 같은 부작용은 바깥 shell에서 수행한다.
이 구조가 단위 테스트, replay와 감사 가능성을 높인다.

**적용 상태: 구현**

### 9.4 Contract-first와 schema versioning

계층 간 의미를 암묵적 dictionary에 맡기지 않고 dataclass와 버전이 있는
`DecisionPacket`으로 고정한다. 숫자는 계산 버전과 함께 전달하며, 계약 변경은
하위 호환성과 소비자를 검토한다.

**적용 상태: 구현**

## 10. LLM과 에이전트

### 10.1 Tool-augmented, neuro-symbolic 구조

TradeFlow는 언어모델의 비정형 언어 처리 능력과 기호적 규칙·수학 도구를 결합한다.
LLM이 모든 추론을 내부적으로 수행하는 구조가 아니라, 검증 가능한 도구가 만든
결과를 언어 계층이 소비한다는 의미다.

**적용 상태: 구현된 경계와 계약. 실제 외부 LLM 연결 범위는 runtime에 따라 다름**

### 10.2 DecisionPacket과 grounded synthesis

`DecisionPacket`은 다음을 고정하는 유일한 합성 입력이다.

- 계산된 수치와 계산 버전
- 규칙 판정과 상태
- 모델 ID, 버전과 champion 여부
- 근거와 source 상태
- 필요한 검토와 누락 정보
- 다음 행동과 요구 문서

LLM은 packet 안의 숫자를 다시 계산하거나 바꾸고, 근거를 새로 만들고, review
상태를 해제하거나, 다른 모델을 champion으로 선택할 수 없다. 합성 결과가 원본
numeric claim과 충돌하면 사용자 응답으로 승격하지 않는다.

**적용 상태: 구현**

### 10.3 Slot filling과 최소 질문

대화형 입력은 필수 정보를 slot으로 구조화한다. 계산을 가능하게 하는 필드를
우선하며 한 번에 질문 수를 제한하고, 여러 거래가 들어오면 새 거래 추가인지 기존
거래 수정인지 구분한다.

**적용 상태: 구현**

### 10.4 인식론적 겸손과 abstention

모델이나 규칙이 알 수 없는 것을 자연스러운 문장으로 메우지 않는다. 정보가
부족하면 `unknown`, `insufficient information`, `review required`로 남기고 어떤
입력이 필요한지 질문한다.

**적용 상태: 구현 원칙**

## 11. UX와 의사결정 지원

### 11.1 대화형 입력과 구조화 화면

대화는 사용자의 의도를 이해하고 누락 정보를 보완하는 데 유용하지만, 금액·날짜,
헤지비율, 신고 상태와 문서 목록은 구조화된 화면에서 비교하고 확인하는 편이
안전하다. 따라서 채팅은 유일한 UI가 아니라 의사결정 workflow의 한 진입점이다.

**적용 상태: 설계. 현재 프론트 완성도는 별도 제품 로드맵으로 관리**

### 11.2 Progressive disclosure

첫 화면에는 결론, 주요 위험과 다음 행동을 보여주고, 사용자가 원할 때 계산 가정,
규칙 근거, 데이터 계보와 모델 비교를 펼친다. 이는 복잡성을 숨기는 것이 아니라
검증 가능한 상세를 단계적으로 노출하는 방식이다.

**적용 상태: 설계**

### 11.3 추천과 실행의 분리

서비스는 헤지 주문, 규제 신고 또는 보험 신청을 자동 실행하지 않는다. 비교 가능한
선택지, 누락 조건과 담당자의 다음 행동을 제공하고 최종 실행은 사람과 권한이 있는
외부 시스템이 담당한다.

**적용 상태: 구현 경계**

## 12. 거버넌스, 보안과 감사

### 12.1 역할분리

knowledge-domain은 규칙·출처·도메인 의미를, platform-runtime은 실행 경로와
운영 안전성을 주로 책임진다. 공유 계약과 모델 승격은 한 역할이 단독으로
확정하지 않는다.

**적용 상태: 거버넌스**

### 12.2 Human-in-the-loop

고위험 규정 판정, 모델 승격, 실제 금융상품 계약과 신고에는 명시적 사람의 검토를
둔다. 자동화 수준은 근거 품질과 실패 비용에 비례해 제한한다.

**적용 상태: 구현 + 거버넌스**

### 12.3 감사 가능성

하나의 결론은 다음 정보로 재현 가능해야 한다.

- 어떤 기업·거래 입력을 사용했는가
- 어떤 데이터 snapshot과 hash를 사용했는가
- 어떤 공식·모델·rulepack 버전을 사용했는가
- 어떤 조건이 참, 거짓 또는 unknown이었는가
- 누가 어떤 승격·검토를 승인했는가
- LLM이 어떤 `DecisionPacket`을 설명했는가

**적용 상태: 대부분 구현. 운영 승인 로그와 영속 결과 저장은 배포 환경 연동 필요**

### 12.4 개인정보와 권한 최소화

기업별 거래, 한도와 은행 호가는 공개 knowledge 저장소에 넣지 않는다. 고객
증거는 tenant별 비공개 저장소에서 관리하고, 계산에 필요한 최소 필드만 전달한다.
LLM에도 원본 문서 전체보다 검증된 구조화 사실을 우선 제공한다.

**적용 상태: 설계 + 일부 구현. 실제 저장소의 접근통제는 배포 환경 책임**

관련 문서: [보안](security.md),
[ADR-0021](../adr/0021-private-eligibility-evidence-snapshots.md)

## 13. 현재 적용하지 않는 이론과 기능

다음 항목은 금융·AI 시스템에서 일반적으로 사용될 수 있지만 현재 TradeFlow의
운영 근거가 아니다.

| 항목 | 현재 미적용 이유 |
|---|---|
| Student-t GARCH | 현재 GARCH-FHS는 경험적 표준화 잔차를 사용함 |
| Black–Scholes와 옵션 가격결정 | MVP의 실행 가능한 헤지 수단과 payoff가 선형 선물환 중심임 |
| 확률미분방정식 기반 환율모형 | 필요한 복잡도와 검증 데이터가 현재 범위를 넘음 |
| ML·딥러닝 환율 방향 예측 | 설명·재현·운영 검증 없이 방향 예측에 의존하지 않음 |
| 강화학습 헤지 | 보상 설계, 안전성, 실제 실행 데이터가 없음 |
| 전사 포트폴리오 평균–분산 최적화 | 현재는 거래 프로그램과 통화 노출 단위 MVP임 |
| 합성 선물환의 실행 호가 사용 | 금리평가 이론값은 기업별 실제 계약 가능 조건이 아님 |
| RAG 결과를 규정의 최종 권위로 사용 | 공식 출처 registry와 검증된 rulepack이 권위 계층임 |
| 완전자동 거래·신고·보험 신청 | 권한, 법률책임과 사람의 확인이 필요함 |
| 규제 자본 VaR·ES 산출 | 현재 지표는 기업 내부 경제적 의사결정 목적임 |

이 항목을 추가하려면 단순 코드 구현만으로 충분하지 않다. 데이터 적합성, 검증
프로토콜, 실패 정책, 설명 계약, 승인 주체와 운영 모니터링을 함께 정의해야 한다.

## 14. 핵심 학술·제도적 계보

| 영역 | 대표 근거 | TradeFlow에서의 용도 |
|---|---|---|
| 시장위험·시나리오 | [Basel Framework MAR30](https://www.bis.org/basel_framework/chapter/MAR/30.htm) | 분위수·시장위험 측정의 개념적 기준 |
| Historical Simulation | [BCBS d457](https://www.bis.org/bcbs/publ/d457.htm) | 역사적 시나리오와 시장위험 검증 참고 |
| EWMA | [RiskMetrics](https://www.msci.com/documents/10199/5915b101-4206-4ba0-aee2-3449d5c7e95a) | 최근 충격 가중 변동성 |
| GARCH | [Bollerslev 1986](https://doi.org/10.1016/0304-4076(86)90063-1) | 조건부 이분산성과 변동성 군집 |
| CVaR | [Rockafellar·Uryasev 2000](https://doi.org/10.21314/JOR.2000.038) | 꼬리손실 기반 헤지비율 비교 |
| 최소분산 헤지 | [Ederington 1979](https://doi.org/10.1111/j.1540-6261.1979.tb02077.x) | 현물·선물환 공분산 기반 비율 |
| 구간예측 검증 | [Christoffersen 1998](https://ideas.repec.org/a/ier/iecrev/v39y1998i4p841-62.html) | coverage와 calibration 해석 |

학술 문헌은 모델의 개념적 근거이며 실제 규정 판정의 법적 근거가 아니다. 외환
규정과 지원제도의 운영 근거는 반드시 `knowledge/source_registry.json`에 등록된
공식 출처와 유효한 rulepack을 사용한다.

## 15. 현재 완성도와 남은 근거 작업

| 영역 | 현재 상태 | 남은 핵심 작업 |
|---|---|---|
| 현금흐름·노출 | 구현 | 다통화·복수 결제수단 범위 확장 |
| 변동성·헤지 모델 | 구현 | 실제 선물환 이력 확보와 경제적 검증 |
| 모델 검증 | 구현 + 거버넌스 | 결과 영속화, 승인 workflow, 추가 진단지표 |
| 규정·지원 규칙 | 구현 | 도메인 전문가 승인과 지속적인 개정 반영 |
| 데이터 registry·snapshot | 구현 | 운영 저장소와 tenant 접근통제 연결 |
| DecisionPacket·LLM 경계 | 구현 | 실제 LLM provider별 합성 검증 운영 |
| UX | 설계/부분 구현 | 대시보드, 거래 타임라인, 비교·근거 화면 |
| 자동 실행 | 의도적으로 제외 | 향후 추진 시 별도 권한·법률·보안 설계 |

따라서 현재의 병목은 새로운 이론을 더 추가하는 것이 아니라, **실제 기업 적용
선물환 호가 확보, 규칙과 모델의 독립 승인, 운영 데이터 계보 및 UX 연결**이다.

## 16. 관련 문서

- [시스템 개요](overview.md)
- [도메인 모델](domain-model.md)
- [데이터와 AI](data-and-ai.md)
- [MVP 아키텍처](../specifications/mvp-architecture.md)
- [공유 계약](../specifications/contracts.md)
- [헤지 모델 검증](../specifications/hedge-model-validation.md)
- [지식 데이터 계획](../specifications/knowledge-data-plan.md)
- [런타임 데이터 소스](../specifications/runtime-data-sources.md)
- [ADR-0007: LLM 실행 경계](../adr/0007-llm-execution-boundary-and-decision-packet.md)
- [ADR-0019: Rulepack 승격](../adr/0019-rulepack-promotion-and-review-policy.md)
- [ADR-0025: Champion–Challenger](../adr/0025-hedge-model-champion-challenger-governance.md)
