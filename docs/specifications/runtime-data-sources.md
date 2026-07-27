---
status: draft
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# 런타임 데이터 소스와 어댑터

## 목적

TradeFlow의 런타임 데이터는 서로 다른 결정을 위해 쓰인다.

| 데이터 | 결정에 쓰이는 지점 | 수집 원칙 |
|---|---|---|
| 기업 거래·예정 현금흐름 | 통화별 순노출, 만기 불일치, 자금 부족 시점 | 기업 원장 API에서 수집 |
| 기준 환율 시계열 | 변동성·시나리오와 결과 재현 | 공식 공공 API에서 스냅샷 수집 |
| 실제 호가·계약 조건 | 실행 가능한 헤지 가격과 비용 비교 | 계약된 은행·브로커 API에서 수집 |
| 법령·지원사업 조건 | 자격·제한·절차 판정 | 검증된 규칙·출처 레지스트리 사용 |

앞의 세 종류는 시점에 따라 값이 달라지므로 API가 적합하다. 법령과 정책은 변경 빈도가
낮고 해석 검토가 필요하므로 API 응답을 곧바로 판단값으로 쓰지 않는다.

## 연결 후보

2026-07-27 현재 공식 문서로 확인한 후보를 다음처럼 분류한다.

| 공급자 | 제공 데이터 | 접근 조건 | TradeFlow 용도 | 결정 |
|---|---|---|---|---|
| 한국은행 ECOS | USD/KRW 일별 매매기준율과 과거 시계열 | ECOS 인증키 | 변동성·기준 시나리오 | 현재 사용 |
| 한국수출입은행 Open API | 통화별 고시 환율 | 무료 활용 신청 키, 신규 `oapi.koreaexim.go.kr` 도메인 | 다통화 기준환율·교차검증 | 다음 어댑터 후보 |
| Microsoft Dynamics 365 Business Central API v2.0 | 판매·구매 송장, 통화, 지급기일, 잔액 | 테넌트와 Entra OAuth 권한 | 거래·예정 현금흐름 원천 | 사용 ERP일 때 매퍼 추가 |
| SAP S/4HANA Cloud OData API | 분개·AR/AP·Treasury 항목 | 고객 시스템 통신 설정과 권한 | 거래·잔액·실현 현금흐름 원천 | 사용 ERP일 때 매퍼 추가 |
| 은행 기업 API/브로커 API | 실시간 또는 지연 호가, 거래 가능 조건 | 법인 계약과 별도 권한 | 최종 실행 가격 | 공급자 계약 후 추가 |

공공기관의 “실시간 업데이트” 표시는 API가 현재 고시값을 돌려준다는 뜻이지
거래 가능한 스트리밍 호가를 보장하지 않는다. ECOS와 수출입은행 값은 기준·분석용이며,
최종 계약 가격은 은행 또는 브로커 응답으로 별도 확인한다.

## 구현된 경계

### `EcosFxAdapter`

- 공식 USD/KRW 일별 시계열을 가져온다.
- 기존 원문 응답을 변경하지 않고 `ECOS_USD_KRW` 스냅샷으로 저장한다.
- 인증키는 요청 시점에만 읽으며 스냅샷과 오류에 포함하지 않는다.

### `JsonTradeFeedAdapter`

ERP마다 다른 필드와 인증을 핵심 도메인으로 들이지 않기 위한 표준 HTTPS JSON 경계다.
ERP 전용 커넥터는 아래 계약으로 변환한 엔드포인트만 제공한다.

```json
{
  "schema_version": "1.0",
  "version": "erp-20260727-090000",
  "observed_at": "2026-07-27T09:00:00+09:00",
  "opening_balances": {"USD": "1200.50"},
  "trades": [{
    "case_id": "EXP-1",
    "direction": "export",
    "currency": "USD",
    "amount": "10000.25",
    "expected_payment_date": "2026-08-31",
    "payment_method": "tt",
    "counterparty_country": "US",
    "confirmed": true,
    "attributes": {"erp_document_id": "9001"}
  }]
}
```

- `direction`: `export` 또는 `import`
- `payment_method`: `tt`, `lc`, `dp`, `da`
- 금액: 반올림 손실을 막기 위해 문자열 사용을 권장
- `observed_at`: 오프셋이 있는 ISO 8601 시각
- `version`: 재수집해도 같은 원장을 가리키는 불변 식별자
- 인증: HTTPS와 선택적 Bearer 토큰
- 안전장치: 10 MiB 기본 상한, 중복 거래 ID·미지원 스키마·미래 관측시각 거부

어댑터는 파싱된 `TradeCase`와 기초잔액을 반환하고 원문 전체를 스냅샷으로 보존한다.
계산 계층은 네트워크 어댑터를 import하지 않고 스냅샷을 읽는 기존 원칙을 유지한다.

고객 거래 스냅샷은 `data/runtime/` 또는 운영 비공개 저장소만 사용하며 Git에 커밋하지
않는다. 공개 ECOS 스냅샷만 재현 테스트를 위해 `data/snapshots/`에 커밋한다.

## 소비와 계보

| 단계 | 구현 | 실패 조건 |
|---|---|---|
| 최신본 선택 | `latest_snapshot_path` | 출처 디렉터리 없음 |
| 봉투 검증 | `read_snapshot` | 해시 또는 경로 identity 불일치 |
| 거래 정규화 | `read_trade_feed_snapshot` | 스키마·버전·관측시각 불일치 |
| 환율 정규화 | `read_ecos_usd_krw_snapshot` | 통계코드·항목·단위·중복·부분응답 오류 |
| 최신성 게이트 | 작업별 `FreshnessPolicy` | 관측 또는 수집 SLA 초과 |
| 계산 입력 | `trade_program_from_snapshot` | 거래피드가 아닌 데이터셋 |
| 결과 계보 | `TradeProgram.input_snapshots` → `DecisionPacket` | source/version/hash 누락 |

이 경로에서는 LLM을 사용하지 않는다. 데이터의 선택, 검증, 정규화, 신선성 판정과
계보 전달은 모두 결정론 코드가 담당한다.

## 다음 연결 순서

1. 실제 사용 ERP와 원장 필드 소유자를 확정한다.
2. 샌드박스 읽기 전용 자격증명을 발급하고 판매·구매 양쪽의 증분 수집 기준을 정한다.
3. ERP 응답을 표준 거래피드로 변환하는 공급자별 매퍼를 추가한다.
4. 한국수출입은행 다통화 기준환율 어댑터를 추가하고 ECOS와 출처 역할을 분리한다.
5. 제휴 은행이 정해지면 호가의 유효시간·bid/ask·수수료를 포함한 실행가격 어댑터를
   별도 계약으로 추가한다.

## 공식 문서

- [한국은행 경제통계시스템](https://ecos.bok.or.kr/)
- [한국수출입은행 환율 정보 Open API](https://www.data.go.kr/data/3068846/openapi.do)
- [Business Central REST API 개요](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/webservices/api-overview)
- [Business Central 판매 송장 리소스](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_salesinvoice)
- [Business Central 구매 송장 리소스](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_purchaseinvoice)
- [SAP Journal Entry Item Read API](https://help.sap.com/docs/SAP_S4HANA_CLOUD/b978f98fc5884ff2aeb10c8fdeb8a43b/8aa29c6ac8234f9a9b975b3900aa002d.html)
