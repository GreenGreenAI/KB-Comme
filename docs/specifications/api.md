---
status: draft
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-26
---

# API 명세 원칙

API가 도입될 때 각 엔드포인트에 다음을 정의한다.

- 목적, 인증 주체와 필요한 권한
- 요청·응답 스키마와 예제
- 오류 코드, 재시도와 멱등성
- 기준일, 통화, 단위와 시간대
- 사용한 규칙·계산 버전과 근거 표현
- 호환성 및 폐기 정책

스키마에서 자동 생성할 수 있는 내용은 수기로 중복 관리하지 않는다.

## 현재 구현된 분석 서비스 계약

`AnalysisService`는 HTTP 프레임워크와 분리된 애플리케이션 경계다. 향후
`POST /v1/analyses` 라우트는 아래 요청을 `snapshot_analysis_request_from_document`로
파싱하고 서비스 결과를 `decision_packet_document`로 반환한다. 라우트와 인증은 아직
구현 범위가 아니며, 외부 채널이 파이프라인을 직접 호출해서는 안 된다.

```json
{
  "schema_version": "1.0",
  "dataset_id": "ERP_TRADE_FEED_V1",
  "snapshot_version": "erp-20260727-090000",
  "program_id": "PROGRAM-1",
  "as_of": "2026-07-27",
  "company": {
    "company_id": "COMPANY-1",
    "name": "Example Exporter",
    "country_code": "KR",
    "is_sme": true,
    "annual_export_usd": "1000000.25",
    "industry_code": "C10",
    "attributes": {}
  }
}
```

- 임의 파일 경로는 받지 않고 레지스트리의 `dataset_id`와 안전한 snapshot version만
  받는다.
- `annual_export_usd`를 포함한 십진 금액은 JSON number가 아닌 문자열이다.
- 알 수 없는 필드는 오탈자로 간주해 거부한다.
- source·hash·schema·kind·freshness 검증을 모두 통과한 거래 스냅샷만 분석한다.
- `as_of`는 실행일보다 미래일 수 없고, 관측·취득일이 `as_of`보다 늦은 스냅샷은
  과거 분석에 사용할 수 없다. 날짜 비교 기준 시간대는 `Asia/Seoul`이다.
- 응답은 현재 `DecisionPacket` schema 1.5의 JSON 표현이며 모든 Decimal은 문자열이다.
  신청 행동에는 `document_set_ids`, 항상 필요한 `required_documents`, 그리고
  필수·조건부·택일 구조를 보존한 `document_requirements`가 포함된다.

| 오류 코드 | 의미 | 권장 HTTP 상태 |
|---|---|---|
| `invalid_request` | 요청 스키마·타입·식별자 오류 | 400 |
| `unknown_dataset` | 등록되지 않은 데이터셋 | 404 |
| `snapshot_not_found` | 지정 버전 없음 | 404 |
| `snapshot_invalid` | 해시·경로·스키마·source 불일치 | 422 |
| `snapshot_stale` | 데이터 사용 가능 SLA 초과 | 409 |
| `wrong_dataset_kind` | 거래피드가 아닌 데이터셋 | 422 |
| `invalid_case_input` | 케이스 fact·evidence 계약 오류 | 422 |

오류 코드는 transport가 변환할 수 있지만, stale 또는 invalid 데이터를 정상 응답으로
승격해서는 안 된다. 같은 요청·스냅샷·규칙 버전은 같은 `packet_id`를 생성한다.
