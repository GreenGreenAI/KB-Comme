---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0008: 근거 결합형 케이스 fact와 규칙 오케스트레이션

- 상태: 제안
- 날짜: 2026-07-27
- 관련: ADR-0002, ADR-0006, ADR-0007, 지식 데이터 수집·구조화 계획

## 배경

실제 규칙팩은 `trade_support_case`와 `fx_compliance` topic을 사용하지만 기존 파이프라인은
데모용 `trade_support`만 호출했다. 또한 `TradeCase.attributes` 같은 자유 입력을 그대로
규칙 fact로 사용하면 사용자가 거래방향·통화 같은 핵심값을 덮거나, 근거 없이 신고예외
fact를 확정할 수 있다.

하나의 규칙이 여러 거래에 적용될 때 rule ID만으로 결과를 식별하면 서로 다른 케이스의
판정을 LLM 합성 단계에서 혼동할 수도 있다.

## 결정

### 1. 규칙 입력은 `FactCatalog`와 `FactAssembler`를 통과한다

`FactCatalog`는 field, type, enum 값과 요구 evidence role을 읽는다. `FactAssembler`는
프로그램과 거래에서 국내기업 여부, 거래방향·통화, USD 계약금액과 수출거래 존재
여부만 결정론적으로 만든다.

나머지 fact는 `FactAssertion`으로 받는다. assertion은 catalog 타입을 만족하고,
해당 케이스 ID를 identifier로 가지며, 요구 role과 동일한 `EvidenceDescriptor`가
`payload.facts`에서 같은 field/value를 명시해야 한다.

### 2. 자유 attributes는 핵심 fact를 덮지 못한다

`CompanyProfile`과 `TradeCase`는 예약된 핵심 fact 이름을 attributes로 받지 않는다.
생성 후 attributes가 변경되더라도 `facts()`에서 핵심값이 마지막에 적용되어 덮어쓰기를
막는다. 케이스 규칙 경로는 attributes를 규정 fact로 사용하지 않는다.

### 3. 케이스별로 실제 두 topic을 실행한다

`TradeFlowPipeline.analyze_cases`는 각 거래에 대해 동일한 `FactBundle`로
`trade_support_case`와 `fx_compliance`를 실행한다. 여러 rulepack은
`KnowledgeRepository.from_json_files`로 하나의 저장소에 적재하며 중복 rule ID는
거부한다.

### 4. 판정 identity는 `(subject_id, rule_id)`다

`RuleDecision`, `PacketDecision`, `DecisionStatusClaim`은 케이스 ID인 `subject_id`를
보존한다. LLM 합성 검증은 복합키를 사용하므로 케이스를 누락하거나 다른 케이스의
상태와 바꾼 결과를 거부한다.

이 변경은 DecisionPacket schema를 `1.1`로 올린다. packet ID는 입력과 분석 내용의
지문을 포함해 같은 프로그램·기준일의 서로 다른 fact 묶음이 같은 ID를 공유하지 않는다.

## 결과

- 근거가 없거나 role만 맞고 실제 값을 명시하지 않은 fact는 규칙에 진입하지 못한다.
- 규정 fact를 LLM이나 자유 attributes가 확정할 수 없다.
- 실제 K-SURE·외국환 규칙이 케이스 단위 DecisionPacket에 도달한다.
- 기존 데모 `analyze` 경로는 호환성을 유지한다.
- 운영 규칙은 상대 역할과 도메인 전문가 검토 전까지 `production_ready=false`다.

## 검증

- fact 타입·enum·근거 role·값 attestation·케이스 scope·불변성 테스트
- 핵심 attributes 덮어쓰기 차단 테스트
- 상호계산 개설 신고 후보의 실제 `fx_compliance` 수직 테스트
- LLM이 케이스 identity를 제거한 합성을 거부하는 테스트
- 전체 경계·단위·문서 검증
