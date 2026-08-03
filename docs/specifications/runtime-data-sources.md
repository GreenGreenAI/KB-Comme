---
status: draft
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# 런타임 데이터 소스와 어댑터

## 목적

KB Comme의 런타임 데이터는 서로 다른 결정을 위해 쓰인다.

| 데이터 | 결정에 쓰이는 지점 | 수집 원칙 |
|---|---|---|
| 기업 거래·예정 현금흐름 | 통화별 순노출, 만기 불일치, 자금 부족 시점 | 기업 원장 API에서 수집 |
| 기준 환율 시계열 | 변동성·시나리오와 결과 재현 | 공식 공공 API에서 스냅샷 수집 |
| 실제 호가·계약 조건 | 실행 가능한 헤지 가격과 비용 비교 | 계약된 은행·브로커 API에서 수집 |
| 법령·지원사업 조건 | 자격·제한·절차 판정 | 검증된 규칙·출처 레지스트리 사용 |
| K-SURE 국별인수방침 | 단기수출보험의 수입국 제한 fact | 공식 K-Sight 응답을 비공개 스냅샷으로 수집 |
| 기업 자격·K-SURE 신용등급 | 기업규모·신용제한·수출자/수입자 등급 fact | 인증된 정규화 feed를 비공개 스냅샷으로 수집 |

앞의 세 종류는 시점에 따라 값이 달라지므로 API가 적합하다. 법령과 정책은 변경 빈도가
낮고 해석 검토가 필요하므로 API 응답을 곧바로 판단값으로 쓰지 않는다.

## 연결 후보

2026-07-27 현재 공식 문서로 확인한 후보를 다음처럼 분류한다.

| 공급자 | 제공 데이터 | 접근 조건 | KB Comme 용도 | 결정 |
|---|---|---|---|---|
| 한국은행 ECOS | USD/KRW 일별 매매기준율과 과거 시계열 | ECOS 인증키 | 변동성·기준 시나리오 | 현재 사용 |
| 한국수출입은행 Open API | 통화별 고시 환율 | 무료 활용 신청 키, 신규 `oapi.koreaexim.go.kr` 도메인 | 다통화 기준환율·교차검증 | AP01 어댑터·typed catalog 구현, 운영 키 연결 대기 |
| Microsoft Dynamics 365 Business Central API v2.0 | 판매·구매 송장, 통화, 지급기일, 잔액 | 테넌트와 Entra OAuth 권한 | 거래·예정 현금흐름 원천 | fail-closed 매퍼 구현, 실제 테넌트 연결 대기 |
| SAP S/4HANA Cloud OData API | AR/AP 개방항목 | 고객 시스템 통신 설정과 권한 | 거래·잔액·실현 현금흐름 원천 | fail-closed 매퍼 구현, 실제 시스템 연결 대기 |
| 은행 기업 API/브로커 API | 실시간 또는 지연 호가, 거래 가능 조건 | 법인 계약과 별도 권한 | 최종 실행 가격 | 공급자 계약 후 추가 |
| K-SURE K-Sight Country Risk Map | 국가별 정상·조건부·인수제한 상태 | 공개 화면의 내부 JSON 계약, 안정성 보장 없음 | 단기수출보험 국가 제한 근거 | 일일 비공개 스냅샷 사용 |

공공기관의 “실시간 업데이트” 표시는 API가 현재 고시값을 돌려준다는 뜻이지
거래 가능한 스트리밍 호가를 보장하지 않는다. ECOS와 수출입은행 값은 기준·분석용이며,
최종 계약 가격은 은행 또는 브로커 응답으로 별도 확인한다.

## 구현된 경계

### 선언형 데이터 레지스트리

운영 데이터셋은 `data/dataset_registry.json`에 등록한다. 각 항목은 다음
계약을 한곳에서 관리한다.

| 필드 | 의미 |
|---|---|
| `dataset_id`, `source_id` | 데이터셋과 원천의 안정적인 식별자 |
| `kind` | `trade_feed`, `fx_series` 등 정규화 결과 종류 |
| `adapter_key`, `parser_key` | 수집 객체와 해석 객체의 명시적 선택 |
| `provider_key` | 자격 증거 dataset이 구현하는 provider 계약 식별자 |
| `payload_schema_version` | 파서가 지원해야 하는 입력 계약 버전 |
| `collection_interval_seconds` | 마지막 취득시각 기준 다음 수집이 필요한 주기 |
| `freshness` | 관측·취득시각 기준 사용 가능 SLA |
| `storage_scope`, `storage_root` | 공개 재현 데이터와 비공개 고객 데이터 분리 |

`DatasetRegistry`와 `ParserRegistry`는 네트워크를 사용하지 않는 domain
객체다. `AdapterRegistry`는 integration leaf에서만 사용하며 등록 시
definition의 source ID와 adapter key가 실제 객체와 일치하는지 확인한다.
API 키, bearer token, 고객 endpoint는 레지스트리에 저장하지 않는다.

### `EcosFxAdapter`

- 공식 USD/KRW 일별 시계열을 가져온다.
- 기존 원문 응답을 변경하지 않고 `ECOS_USD_KRW` 스냅샷으로 저장한다.
- 인증키는 요청 시점에만 읽으며 스냅샷과 오류에 포함하지 않는다.

### `KoreaEximFxAdapter`

- 공식 신규 도메인의 `exchangeJSON`과 `data=AP01`만 호출한다.
- `authkey`는 `KOREAEXIM_API_KEY` 또는 생성자에서 읽고 snapshot·repr·오류에
  포함하지 않는다.
- `searchdate`를 명시적으로 요구하며 요청 날짜와 snapshot 관측일을 일치시킨다.
- HTTP 200이어도 `result=2` DATA 코드 오류, `3` 인증 오류, `4` 일일 한도 소진은
  실패한다.
- 공식 응답의 `CUR_UNIT`, `TTB`, `TTS`, `DEAL_BAS_R`, `BKPR`, 환가료율과
  서울외국환중개 값을 `ReferenceFxCatalog`에 보존한다.
- `JPY(100)`처럼 100통화 단위로 고시된 행은 raw 단위와 배수를 보존하고
  `krw_per_currency_unit`에서만 1통화 단위로 환산한다.
- 쉼표가 포함된 숫자는 `Decimal`로 정규화하고, 중복 통화·부분 필드·음수·0 이하
  매매기준율은 거부한다.

이 catalog는 다통화 분석 기준과 ECOS 교차검증용이다. TTB/TTS가 포함되어 있어도
기업별 실제 체결 가능 호가, 수수료 또는 유효시간을 증명하지 않으므로 실행가격으로
사용하지 않는다.

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

### ERP 공급자별 매퍼

`BusinessCentralInvoiceMapper`와 `SapReceivablePayableMapper`는 공급자 응답을 위 표준
거래피드로 변환하는 결정론 객체다. 공급자 필드는 핵심 도메인이나 데이터셋 레지스트리에
노출하지 않으며, 생성 결과는 기존 `ERP_TRADE_FEED_V1` 계약으로 다시 검증한다.

Business Central은 다음 정책을 적용한다.

- 판매송장은 `Open` 상태와 공식 `remainingAmount`를 요구한다.
- 구매송장의 `totalAmountIncludingTax`는 미결제잔액이 아니다. 고객별 커넥터가 원장과
  대조해 제공하는 `tradeflowRemainingAmount`가 없으면 실패한다.
- 판매·구매 응답의 모든 OData 페이지가 수집된 뒤 매퍼를 호출해야 한다.

SAP는 범용 Journal Entry Item이 아니라 Receivable Payable Item 투영을 사용한다.
고객 또는 공급자 중 하나의 계정 역할, `RblPyblItemIsCleared`,
`RblPyblItemIsObsolete`, `AmountInTransactionCurrency`, `TransactionCurrency`와
`NetDueDate`를 명시적으로 요구한다.

두 매퍼 모두 결제방식을 추정하지 않는다. 공급자 확장 필드 또는 검토된 고객별 기본
정책이 필요하다. JSON 파서는 금액을 `Decimal`로 유지해야 하며 binary float가 전달되면
거부한다. 부분 OData 페이지, 중복 ID, 미래 수정시각과 증명할 수 없는 상태도 실패한다.

### `BizinfoSupportAdapter`

- 기업마당 공식 API의 지원사업 목록을 JSON으로 수집한다.
- 인증키는 `BIZINFO_API_KEY` 환경변수나 생성자 인자로만 전달한다.
- 원문 응답은 `BIZINFO_SUPPORT_API` 스냅샷으로 저장하고, 계산 계층에서는
  `SupportProgramCatalog`와 `SupportProgram` 객체로 읽는다.
- 공고 ID, 제목, 주관기관, 수행기관, 지원분야, 대상, 신청기간, URL, 해시태그를
  정규화한다. 필수 필드 누락과 중복 공고 ID는 실패 처리한다.
- 목록에 포함되었다는 사실은 지원 자격 판정이 아니다. 자격·우선순위·추천 여부는
  공고 상세 조건을 근거로 만든 별도 검토 규칙에서 결정한다.

기업마당 목록은 48시간 관측·수집 SLA를 적용한다. API 장애 시에는 공통 수집
오케스트레이터가 마지막 정상 스냅샷의 신선도를 확인한 뒤 사용 여부를 결정한다.

### 공통 수집 오케스트레이션

`CollectionOrchestrator`는 외부 스케줄러가 호출하는 결정론적 실행 경계다. 최신
스냅샷이 없거나 stale이거나 `collection_interval_seconds`가 경과했을 때만 수집하며,
요청별 최대 5회까지 재시도한다. 수집 성공 파일도 레지스트리 파서로 다시 읽어
source·hash·schema·freshness 검증을 통과해야 `collected`가 된다.

수집이 실패하면 마지막 정상 스냅샷을 동일한 검증 경로로 확인한다. 아직 fresh인
경우에만 `fallback`, 그 외에는 `failed`다. 수집 주기 판정, 재시도 횟수, fallback
허용에는 LLM을 사용하지 않는다. 운영 스케줄러는 이 오케스트레이터를 주기적으로
호출할 뿐 최신성이나 사용 가능 여부를 별도로 추정하지 않는다.

고객 거래 스냅샷은 `data/runtime/` 또는 운영 비공개 저장소만 사용하며 Git에 커밋하지
않는다. 공개 ECOS 스냅샷만 재현 테스트를 위해 `data/snapshots/`에 커밋한다.

### `JsonEligibilityEvidenceAdapter`

중소기업 확인자료와 K-SURE 신용정보는 기관별 원 응답을 규칙 fact로 직접 사용하지
않는다. 고객별 커넥터가 다음 schema 1.0으로 정규화한 HTTPS feed를 제공하며,
`COMPANY_QUALIFICATION_EVIDENCE_V1`과 `KSURE_CREDIT_EVIDENCE_V1`은 항상
`data/runtime/` 범위에 저장한다.

```json
{
  "schema_version": "1.0",
  "version": "company-20260727-v1",
  "observed_at": "2026-07-27T00:00:00+00:00",
  "provider_key": "company_qualification",
  "records": [{
    "evidence_id": "company:C1:20260727",
    "company_id": "C1",
    "subject_kind": "company",
    "subject_id": "C1",
    "valid_until": "2026-08-27T00:00:00+00:00",
    "facts": {"company.size": "small"}
  }]
}
```

- endpoint는 HTTPS만 허용하고 bearer token은 생성자 또는 환경변수에서만 읽는다.
- endpoint와 token은 repr, 오류, 스냅샷에 기록하지 않는다.
- schema·중복 evidence ID·시간대·주체 scope를 수집 전후 두 번 검증한다.
- root와 record의 미정의 필드는 거부해 credential이나 계약 밖 데이터의 저장을 막는다.
- dataset definition의 provider key와 payload provider key가 다르면 거부한다.
- 전체 payload의 SHA-256이 각 `EvidenceMetadata`에 연결된다.
- `company_id`는 모든 record에 필수다. 같은 `case_id`가 다른 tenant에 존재해도
  `SnapshotEligibilityEvidenceProvider`가 현재 회사의 record만 선택한다.
- snapshot freshness와 record `valid_until`은 별도 게이트다. 둘 중 하나라도
  만료되면 fact assertion을 만들 수 없다.
- provider가 만든 record도 `EligibilityEvidenceAssembler`의 trusted source,
  catalog type, conflict 검사를 다시 통과해야 한다.

### `KsureCountryPolicyAdapter`

- 공식 K-Sight Country Risk Map 화면이 사용하는 전체 국가 정책 응답을 POST로 수집한다.
- 국가 디렉터리와 정상·조건부·인수제한·심층감시 필터를 각각 조회해 alpha-2
  국가코드 집합을 교차검증하고 typed catalog로 만든다.
- 중복 국가, 디렉터리에 없는 필터 결과, unknown 상태와 누락 국가는 fail-closed한다.
- 원문 이용·재배포 조건과 내부 API 안정성이 확인되지 않았으므로 스냅샷은
  `data/runtime/`에만 저장하고 48시간 freshness gate를 적용한다.
- `bind_country_policy`는 exact snapshot source·version·hash를 포함한 evidence와
  `counterparty.country_restricted` fact를 함께 생성한다.

## 소비와 계보

| 단계 | 구현 | 실패 조건 |
|---|---|---|
| 최신본 선택 | `latest_snapshot_path` | 출처 디렉터리 없음 |
| 봉투 검증 | `read_snapshot` | 해시 또는 경로 identity 불일치 |
| 거래 정규화 | `read_trade_feed_snapshot` | 스키마·버전·관측시각 불일치 |
| 환율 정규화 | `read_ecos_usd_krw_snapshot` | 통계코드·항목·단위·중복·부분응답 오류 |
| 다통화 기준환율 | `KoreaEximReferenceFxV1Parser` | API result·필드·통화단위·숫자·관측일 오류 |
| 자격 증거 정규화 | `EligibilityEvidenceV1Parser` | schema·주체·시간대·중복·scalar fact 오류 |
| tenant 투영 | `SnapshotEligibilityEvidenceProvider` | 회사 불일치 record 제외·snapshot stale |
| 최신성 게이트 | 작업별 `FreshnessPolicy` | 관측 또는 수집 SLA 초과 |
| 계산 입력 | `trade_program_from_snapshot` | 거래피드가 아닌 데이터셋 |
| 결과 계보 | `TradeProgram.input_snapshots` → `DecisionPacket` | source/version/hash 누락 |

이 경로에서는 LLM을 사용하지 않는다. 데이터의 선택, 검증, 정규화, 신선성 판정과
계보 전달은 모두 결정론 코드가 담당한다.

## 다음 연결 순서

1. 실제 사용 ERP와 원장 필드 소유자를 확정한다.
2. 샌드박스 읽기 전용 자격증명을 발급하고 판매·구매 양쪽의 증분 수집·페이지 순회
   기준을 정한다.
3. 구현된 공급자별 매퍼를 샌드박스 응답 fixture와 대조하고 고객별 확장 필드를 확정한다.
4. 한국수출입은행 운영 API 키를 연결하고 수집 스케줄·실패율을 관측한다.
5. 제휴 은행이 정해지면 호가의 유효시간·bid/ask·수수료를 포함한 실행가격 어댑터를
   별도 계약으로 추가한다.

## 공식 문서

- [한국은행 경제통계시스템](https://ecos.bok.or.kr/)
- [한국수출입은행 환율 정보 Open API](https://www.data.go.kr/data/3068846/openapi.do)
- [Business Central REST API 개요](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/webservices/api-overview)
- [Business Central 판매 송장 리소스](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_salesinvoice)
- [Business Central 구매 송장 리소스](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/resources/dynamics_purchaseinvoice)
- [SAP Receivable Payable Item](https://help.sap.com/docs/SAP_S4HANA_CLOUD/c0c54048d35849128be8e872df5bea6d/139895f571ce4417b9bd3b01eb3323f7.html)
- [SAP C1 released CDS view catalog](https://help.sap.com/docs/SAP_S4HANA_CLOUD/c0c54048d35849128be8e872df5bea6d/95c4b490537a415e834076e07abccb1c.html)
- [K-Sight Country Risk Map](https://ksight.ksure.or.kr/rsrch/nation/nationView)
- [K-SURE 단기수출보험(선적후) 이용요건](https://www.ksure.or.kr/rh-kr/cntnts/i-118/web.do)
