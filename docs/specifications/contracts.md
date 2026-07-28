---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# 공유 계약 변경 규칙

`contracts/` 또는 외부에 노출된 `domain/` 모델 변경은 다음 순서를 따른다.

1. 사용 사례와 호환성 영향을 문서화한다.
2. 계약과 기대 동작을 나타내는 테스트를 먼저 변경한다.
3. 지식·도메인과 플랫폼·런타임 양쪽 영향을 PR에 기록한다.
4. 각 구현을 새 계약에 맞춘다.
5. 상대 담당자 승인과 전체 검증을 완료한다.

호환되지 않는 변경은 마이그레이션 또는 명시적인 버전 전략 없이 병합하지 않는다.

## DecisionPacket 합성 계약

결정론 분석과 LLM 합성의 경계는
[`DecisionPacket`](../adr/0007-llm-execution-boundary-and-decision-packet.md)으로
고정한다.

| 필드 | 의미 | LLM 변경 허용 |
|---|---|---|
| `packet_id`, `schema_version`, `as_of` | 추적성과 계약 버전 | 아니요 |
| `inputs` | 정규화된 사실 | 아니요 |
| `exposures` | 도구가 계산한 수치 | 아니요 |
| `decisions` | 규칙 판정, source/claim ID와 구조화된 후보 결과 | 아니요 |
| `actions` | 적용 규칙의 기관·행동·기한·미충족요건·필요문서 세트·절차·근거 | 아니요 |
| `evidence` | 판정과 계산의 근거 | 아니요 |
| `review_required`, `review_reasons` | 사람 검토 게이트 | 아니요 |

LLM 출력은 `SynthesisResult`로 구조화한다. 설명문은 비권위적이며, 함께 반환된
판단 상태·수치 주장·근거 ID·검토 상태가 `validate_synthesis`를 통과해야 한다.
검증 실패 시 생성 설명을 폐기하고 패킷 기반 대체 응답 또는 사람 검토를 사용한다.

## 케이스 fact 계약

실제 규칙 topic의 입력은 [ADR-0008](../adr/0008-evidence-bound-case-facts.md)의
`FactBundle`을 사용한다.

- catalog에 없는 fact는 거부한다.
- supplemental fact는 evidence ID가 필수다.
- evidence role, 케이스 identifier와 `payload.facts`의 field/value가 모두 일치해야 한다.
- 프로그램·거래에서 결정론적으로 얻는 core fact는 assertion으로 덮지 못한다.
- 케이스 판정 identity는 `rule_id`가 아니라 `(subject_id, rule_id)`다.

## 기한 파생과 실행계획 계약

- 상호계산 기장 기한은 기준일에서 30일, 결산잔액 신고와 지급·수령 기한은
  결산기간 종료일에서 3개월을 달력 기준으로 계산한다.
- 신고 완료일과 지급·수령 완료일은 독립적으로 평가한다.
- 파생 사실은 `calculation` evidence가 케이스 ID와 정확한 field/value를
  증명한 경우에만 규칙 입력이 된다.
- `RuleDecision.matched=true`인 규칙만 `actions`로 투영한다. 판정 상태는
  초안 여부나 출처 상태를 포함하므로 적용성의 대용으로 사용하지 않는다.
- 기한·실행계획을 처음 추가한 schema는 `1.2`이며, 현재 계약은 아래
  분류·통합 필드를 포함한 `1.3`이다.

## 판정 분류와 실행계획 통합

- 판정은 `candidate`, `excluded`, `missing_information`, `expert_review`,
  `source_unusable`, `urgent_action`을 복수 태그로 가질 수 있다.
- 분류는 `matched`, 판정 상태, 구조화된 `timing`에서만 파생한다.
- 같은 케이스·기관·행동·시점·기한의 실행계획은 하나로 통합한다.
- 통합 결과의 `rule_ids`, 미충족요건, 문서, 절차, source/claim ID는
  최초 등장 순서로 모두 보존한다.
- 판정 분류·통합을 추가한 schema는 `1.3`, K-SURE 상품 ID를 보존한 계약은
  `1.4`이다. `1.5`는 `document_set_ids`와 필수·조건부·택일
  `document_requirements`를 실행계획에 보존한다. 현재 `1.6`은 명시적
  champion, 모델 버전, 헤지비율, 시나리오 범위, shortfall과 비용을
  `hedge_decisions`에 보존한다.

## 헤지 모델 결과 계약

- 계산 계층은 `HedgeDecisionInput`의 구조를 충족하는 결정론적 결과만 전달한다.
- 결과가 하나 이상이면 정확히 하나의 `champion_model_id`를 명시한다.
- 같은 패킷에 동일 `model_id`를 두 번 넣을 수 없다.
- `recommended_ratio`, adverse/forecast rate, breach probability,
  expected shortfall과 estimated cost는 LLM이 변경할 수 없는 numeric claim이다.
- 합성 결과의 모델 ID·버전·champion 여부·상태는 패킷과 정확히 일치해야 한다.
- challenger 비교 결과를 함께 담을 수 있지만, `is_champion=false` 결과는 운영
  추천으로 승격되지 않는다.
- 런타임이 이 계약을 호출하는 작업은 역할 B가 수행하며, 계약 추가만으로 기존
  `analyze_hedge()` 호출 경로가 자동 교체되지는 않는다.

## 신청서류 계약

- 규칙은 자유 문자열 `required_documents`와 버전형 `document_set_ids`를 동시에
  사용할 수 없다.
- `required_documents`에는 모든 케이스에 필요한 서류만 평탄화한다.
- `conditional`은 적용 조건 설명을, `one_of`는 두 개 이상의 선택지와 선택에
  필요한 `selector_field`를 반드시 가진다.
- 신청서류 세트의 source/claim ID는 자격 규칙의 근거와 합쳐져 판정과 실행계획에
  보존되며, stale 또는 확인 불가 출처를 정상 서류 안내로 승격하지 않는다.
- LLM은 서류 그룹을 설명할 수 있지만 조건부 서류를 필수로 바꾸거나 택일 서류를
  임의로 선택할 수 없다.

## K-SURE 케이스 계약

- 기업규모, 공통 신용제한, 수출자·수입자 등급, 국별 제한, 결제기간,
  금융목적, 은행 상담 여부는 `KsureCaseProfile`로 입력한다.
- 입력된 각 값은 해당 케이스를 명시하고 정확한 field/value를 증명하는
  evidence ID를 가져야 한다.
- 적용된 상품은 실행계획의 `product_ids`에 보존한다. 상품 ID가 다르면
  같은 행동명이라도 서로 다른 신청 업무이므로 병합하지 않는다.
- 은행 상담 미완료처럼 보완 가능한 조건은 실행계획의 구조화된
  `requirements`에 포함한다.

## 규칙 승격과 결과 검토 계약

- `production_ready`는 규칙 자체의 출처·정답·승인 준비 상태다.
- `review_policy`는 일치 결과를 자동 후보로 내보낼지 전문가 확인으로 보낼지 정한다.
- `always_expert` 규칙은 `production_ready=true`여도
  `EXPERT_CONFIRMATION_REQUIRED`를 반환한다.
- LLM은 이 정책을 제거하거나 `ELIGIBLE_CANDIDATE`로 승격할 수 없다.
- 규칙팩을 active로 전환하려면 golden suite와 세 역할의 artifact-bound 승인이 모두
  필요하다.
