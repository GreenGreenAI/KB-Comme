---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0022: 한국수출입은행 다통화 기준환율 catalog

- 상태: 제안
- 날짜: 2026-07-27

## 배경

ECOS adapter는 USD/KRW 과거 시계열을 제공하지만 수출입 거래의 JPY, EUR, CNY 등
다통화 기준환율을 직접 제공하지 않는다. 한국수출입은행 AP01 응답은 다통화 환율과
송금 받을/보낼 때 환율을 포함하지만, HTTP 200 안에 오류 result를 반환하고 통화별
고시단위도 `JPY(100)`처럼 다르다. 이를 단순 `currency → float`로 만들면 오류 응답,
단위와 출처 역할을 잃는다.

## 고려한 선택지

1. 기존 `FxSeries`에 최신 다통화 행을 섞는다. 시계열과 단일 기준일 catalog의 의미가
   달라 관측·완전성 계약이 불명확해진다.
2. 응답의 `DEAL_BAS_R`만 dictionary로 저장한다. 단순하지만 단위·공식 원문·다른
   공식 필드를 잃는다.
3. 별도 `ReferenceFxCatalog`와 AP01 전용 parser/adapter를 둔다.

## 결정

3번을 선택한다.

- 신규 공식 도메인 `oapi.koreaexim.go.kr`의 `exchangeJSON` AP01을 사용한다.
- `authkey`, `searchdate`, `data=AP01`을 명시하고 search date 없는 호출은 허용하지
  않는다.
- 인증키는 런타임에만 읽으며 URL이 포함된 예외를 그대로 노출하지 않는다.
- HTTP 상태와 별도로 공식 `result` 1만 성공이다. 2, 3, 4와 미지 코드는 실패한다.
- 공식 응답 필드 전체를 schema 1.0 wrapper에 보존하고 exact allowlist로 검증한다.
- 통화코드는 `AAA` 또는 `AAA(n)`만 허용하며 raw 표기, 고시 배수와 Decimal 값을
  함께 보존한다. 1통화 단위 값은 명시적 property로만 계산한다.
- 중복 통화, 빈/부분 응답, 비유한·음수 값, 0 이하 매매기준율은 fail-closed한다.
- dataset kind는 `reference_fx_catalog`로 두어 ECOS `fx_series` 및 향후 은행 실행
  호가 계약과 분리한다.
- API 응답은 공개 기준데이터 snapshot으로 저장하되 인증키는 포함하지 않는다.

## 결과

다통화 거래를 하나의 공식 기준일 catalog로 환산하고 ECOS USD/KRW와 교차검증할 수
있다. 다만 이 값은 분석 기준이며 기업별 스프레드·수수료·유효시간이 있는 실행 호가를
대체하지 않는다. 운영 키 발급과 정기 수집은 배포 환경에서 별도로 설정한다.

## 검증

- 공식 성공/error result fixture 테스트
- `JPY(100)` 단위와 comma Decimal 정규화 테스트
- 부분·중복·미지 필드·음수·빈 응답 fail-closed 테스트
- 신규 도메인·AP01·검색일·credential 비노출 adapter 테스트
- snapshot 관측일과 parser 결과 교차검증 및 dataset registry 테스트
