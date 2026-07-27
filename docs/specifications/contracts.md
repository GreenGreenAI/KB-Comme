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
| `actions` | 적용 규칙의 기관·행동·기한·미충족요건·필요문서·절차·근거 | 아니요 |
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
- 이 계약을 포함하는 `DecisionPacket` schema version은 `1.3`이다.
