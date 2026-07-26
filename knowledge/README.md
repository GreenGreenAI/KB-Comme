# Knowledge data

이 디렉터리는 역할 A가 관리하는 공식 출처 레지스트리와 실행 가능한 규칙 팩을
보관한다.

## Source registry

`source_registry.json`은 출처의 신원, 공식성, 효력기간과 이용 조건을 관리한다.
동적 데이터의 개별 버전·관측시점·해시는 `data/snapshots/`의 `SnapshotRef`가
관리하며, 두 레코드는 같은 `source_id`로 연결한다.

주요 필드:

- `official`: 공식 기관이 제공하는 출처인지 여부
- `verified`: 역할 A가 출처와 식별정보를 확인했는지 여부
- `effective_from`, `effective_to`: 규정·문서의 효력기간
- `freshness_required`: 자동 판정에 스냅샷 신선성이 필요한지 여부
- `usage_policy_url`: 이용·저작권 정책
- `attribution`: 결과 또는 재배포 시 표시할 출처

한국은행 ECOS 정보 이용 시 한국은행을 출처로 표시해야 한다. 세부 이용 조건은
registry의 `usage_policy_url`을 기준으로 확인한다.

## Rulepacks

규칙의 기본 실패 효과는 `reject`다. 충족 가능한 조건을 조건부 후보로 표현하려면
명시적으로 다음처럼 작성한다.

```json
{
  "field": "company.has_required_document",
  "operator": "eq",
  "value": true,
  "description": "필수 서류 제출",
  "failure_effect": "conditional"
}
```

사실이 누락된 경우에는 `failure_effect`와 관계없이
`INSUFFICIENT_INFORMATION`이 반환된다. 규칙은 공식 출처 확인, 정답 사례와 상대
담당자 리뷰를 마친 뒤에만 `production_ready`로 전환한다.
