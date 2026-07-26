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
| `decisions` | 규칙 엔진의 판정과 조건 | 아니요 |
| `evidence` | 판정과 계산의 근거 | 아니요 |
| `review_required`, `review_reasons` | 사람 검토 게이트 | 아니요 |

LLM 출력은 `SynthesisResult`로 구조화한다. 설명문은 비권위적이며, 함께 반환된
판단 상태·수치 주장·근거 ID·검토 상태가 `validate_synthesis`를 통과해야 한다.
검증 실패 시 생성 설명을 폐기하고 패킷 기반 대체 응답 또는 사람 검토를 사용한다.
