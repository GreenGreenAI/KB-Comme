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
- `source_kind`, `authority_level`: 법령·공식안내·API 등 출처 유형과 권위
- `extract_path`: 사람이 검증한 구조화 추출본
- `refresh_interval_days`: 다음 원문 변경 확인 기한

한국은행 ECOS 정보 이용 시 한국은행을 출처로 표시해야 한다. 세부 이용 조건은
registry의 `usage_policy_url`을 기준으로 확인한다.

## Curated extracts

`extracts/`는 공식 원문에서 자동 판정에 필요한 주장만 정규화한 검증본이다. 원문
전체의 복사본이 아니며 각 claim은 원문 위치, 정규화 요약, 임계값·허용값과 자동화
한계를 가진다. 레지스트리의 `content_hash`는 추출 JSON 전체를 canonical JSON으로
직렬화한 SHA-256 값이다.

출처 변경 시 기존 파일을 조용히 덮어쓰지 않는다. 새 기준일 또는 문서 버전의 extract를
추가하고, 이전 source의 `effective_to`와 새 source의 `effective_from`을 연결한다.

## Source monitoring

`source_monitors.json`은 각 extract의 공식 URL과 문서 신원을 확인할 필수 표지를
정의한다. 다음 명령은 HTTP 상태, 최종 URL, 응답 SHA-256과 표지 누락 여부를
점검한다.

```powershell
$env:PYTHONPATH="src"
python scripts/check_sources.py
```

응답 본문은 저장하지 않는다. 출처별 이용·재배포 조건을 확인하기 전까지는
`metadata_and_fingerprint_only` 정책을 유지한다. 표지가 하나라도 사라지면 해당
출처를 최신으로 간주하지 않고, 연결된 규칙의 자동 판정을 중단한 뒤 역할 A가
원문 변경 여부를 확인한다. 응답 SHA-256은 실행 시점의 감사 정보이며 동적 HTML의
고정 버전 식별자로 사용하지 않는다.

## Fact catalog

`fact_catalog.json`은 규칙이 참조할 수 있는 입력 필드의 이름, 형식, 단위와 필요한
근거 역할을 정의한다. 규칙팩에 catalog 밖의 필드를 추가하면 검증 테스트가 실패한다.
`UNKNOWN`이나 누락값을 임의로 유리한 값으로 치환하지 않는다.

## Exception catalogs

`exception_catalogs/`는 한 조문에 다수의 예외가 있는 경우 전체 목록과 필요한
증빙, 자동화 수준을 관리한다. 규칙 입력은 `exception_applies=true/false` 같은
포괄 boolean을 사용하지 않고 `article_5_10_22`처럼 조문과 연결되는 enum을
사용한다. `none`은 모든 예외를 검토해 해당하지 않음을 증빙한 경우에만 입력하며,
미분류 상태는 누락 또는 `unknown`으로 유지한다. LLM은 예외 코드를 확정하지 않고
결정론적 규칙 결과를 설명하는 역할만 맡는다.

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

## 승격 절차

1. 역할 A가 공식 원문과 구조화 extract를 교차 확인한다.
2. 규칙의 모든 field를 fact catalog에 등록하고 증거 생성 경로를 정한다.
3. 경계값 바로 아래·동일·바로 위 정답 사례를 추가한다.
4. 역할 B가 파서, 실행 경계, 최신성 및 실패 동작을 검토한다.
5. 도메인 전문가가 신고·상품 후보 결과를 확인한다.
6. 위 검토가 끝난 규칙만 `production_ready=true`로 변경한다.

현재 `ksure_mvp_candidates.json`과 `fx_compliance_mvp.json`은 공식 공개정보를
구조화한 초안이며 자동 확정 판정에 사용하지 않는다.
