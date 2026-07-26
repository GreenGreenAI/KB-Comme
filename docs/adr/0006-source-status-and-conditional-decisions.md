---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0006: 출처 상태 합성과 조건부 판정 계약

- 상태: 제안 (역할 B 승인 대기)
- 날짜: 2026-07-27
- 관련: ADR-0003, ADR-0004, MVP 아키텍처 정의서 §5.4, §6.2, §6.3

## 배경

ADR-0003은 출처 시행 상태와 스냅샷 신선성이 서로 다른 축임을 확인했지만 최종 상태의
합성 순서를 정하지 않았다. ADR-0004는 `CONDITIONAL` 상태를 도입했지만 조건을 자유
문장으로 둘지 구조화할지 역할 A 결정으로 남겼다.

이 두 빈칸을 그대로 두면 같은 출처가 호출 위치에 따라 다르게 평가되고, 조건부 후보의
해결 방법을 LLM이나 화면이 문장에서 다시 추론하게 된다.

## 고려한 선택지

### 출처 상태

| 선택지 | 장점 | 비용 |
|---|---|---|
| 시행 상태와 신선성을 호출자가 별도로 해석 | 유연함 | 호출자마다 우선순위가 달라짐 |
| 상태를 모두 독립 boolean으로 반환 | 정보 보존 | 최종 판정마다 동일한 합성 코드가 반복됨 |
| **단일 우선순위로 합성** | 판정이 재현 가능 | 가장 중요한 실패 하나만 최종 상태로 노출 |

### 조건부 판정

| 선택지 | 장점 | 비용 |
|---|---|---|
| `status_reasons` 자유 문장만 사용 | 구현이 단순 | 도구와 화면이 해결 조건을 다시 추론해야 함 |
| 모든 조건을 별도 Workflow로 변환 | 실행성이 높음 | 아직 Task 모델이 확정되지 않음 |
| **구조화 requirement를 판정에 포함** | 기계 처리 가능, Workflow와 분리 | 응답 계약 필드가 늘어남 |

## 결정

### 1. 출처 상태는 다음 순서로 합성한다

```text
UNVERIFIED
→ FUTURE
→ EXPIRED
→ FRESHNESS_UNKNOWN
→ STALE
→ ACTIVE
```

앞 단계가 뒤 단계보다 우선한다. 최신 스냅샷을 수집해도 미검증 출처가 공식 근거가
되거나 만료된 규정이 다시 유효해지지 않기 때문이다.

`freshness_required=false`인 정적 출처는 신선성 입력이 없어도 시행 상태가 유효하면
`ACTIVE`다. 동적 시장 데이터처럼 `freshness_required=true`인 출처는 신선성 정보가
없으면 `FRESHNESS_UNKNOWN`이며 자동 판정에 사용할 수 없다.

### 2. 출처 상태별 판정 동작을 고정한다

- 누락된 source ID: `EXPERT_CONFIRMATION_REQUIRED`
- `EXPIRED`: `SOURCE_EXPIRED`
- `UNVERIFIED`, `FUTURE`, `FRESHNESS_UNKNOWN`, `STALE`:
  `EXPERT_CONFIRMATION_REQUIRED`
- 모든 출처가 `ACTIVE`: 조건 평가를 계속 진행

누락된 출처를 만료로 표현하지 않는다. 누락과 만료는 해결 방법이 다르기 때문이다.

### 3. 조건 실패 효과를 `REJECT`와 `CONDITIONAL`로 구분한다

- `REJECT`: 알려진 실패는 `NOT_ELIGIBLE`
- `CONDITIONAL`: 알려진 실패는 `CONDITIONALLY_ELIGIBLE`
- 사실 자체가 누락된 경우: 효과와 무관하게 `INSUFFICIENT_INFORMATION`
- hard rejection과 conditional failure가 함께 있으면 `NOT_ELIGIBLE`

조건부 판정은 조건을 충족하지 않았다는 사실을 알고 있고, 그 조건을 후속 행동으로
해결할 수 있을 때만 사용한다. 사실이 없어서 판정하지 못하는 경우를 조건부 가능으로
포장하지 않는다.

### 4. 조건부 결과에 구조화 requirement를 포함한다

각 requirement는 다음을 가진다.

```text
field / operator / expected_value / current_value / description
```

이는 판정 결과이며 아직 실행 Task가 아니다. Workflow 계층은 이후 이 값을 사용해
서류 제출, 상담 또는 조건 변경 Task를 만들 수 있다. LLM은 requirement를 설명할 수
있지만 새 조건을 만들거나 판정 상태를 승격하지 않는다.

## 결과

- `SourceStatus`에 `FRESHNESS_UNKNOWN`, `STALE` 추가
- `SourceRecord.status_on`이 시행 상태와 신선성을 합성
- `KnowledgeService.evaluate`가 source별 신선성을 선택 입력으로 받음
- `Condition.failure_effect`와 `RuleDecision.requirements` 추가
- `CONDITIONALLY_ELIGIBLE`은 사람 검토 대상으로 유지
- 동적 ECOS 출처를 source registry에 등록

## 검증

- 출처 상태 우선순위와 freshness 누락·만료·stale 조합을 단위 테스트한다.
- 알려진 보완 가능 실패가 구조화 requirement를 반환하는지 검사한다.
- 누락 fact가 조건부가 아니라 정보 부족으로 남는지 검사한다.
- hard rejection이 조건부 실패보다 우선하는지 검사한다.
- ECOS registry의 source ID가 커밋된 스냅샷 identity와 일치하는지 검사한다.
