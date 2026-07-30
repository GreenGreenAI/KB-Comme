---
status: accepted
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-30
---

# Currencycloud Demo 및 KRX benchmark 연결

## 데이터 등급

두 provider의 결과는 서로 대체하지 않는다.

- Currencycloud Demo `Get Detailed Rates`: 인증 계정과 미래 conversion date에 대한
  provider indicative quote다. 문서상 conversion을 예약해야 rate가 고정되므로
  `provider_indicative_forward_quote`, `booking_required=true`로 저장한다.
- KRX 미국달러선물: 실제 거래소 상장선물의 일별 시장 benchmark다.
  `listed_fx_future`로 저장하며 기업별 OTC 선도환 호가로 표시하지 않는다.

두 데이터 모두 `observed_forward_quote` 이력 100건을 요구하는 최소분산 모델의
운영 승격 조건을 직접 충족하지 않는다. Currencycloud live booking 또는 기업별
은행 RFQ/TMS 이력이 확보되어야 해당 조건을 충족할 수 있다.

## 설정

비밀값은 Git에 저장하지 않는다.

```text
CURRENCYCLOUD_DEMO_LOGIN_ID
CURRENCYCLOUD_DEMO_API_KEY
KRX_OPEN_API_KEY
```

KRX는 Data Marketplace 가입·인증키 발급·`선물 일별매매정보(주식선물外)` API
활용 승인이 필요하다. Currencycloud는 Demo API key 등록이 필요하다.

## 현재 검증 상태

2026-07-30 승인된 KRX 인증키로 공식 endpoint에 실제 HTTPS 요청을 보내
2026-07-29 미국달러선물 outright 40건을 수신·정규화했다. 같은 응답의 음수 가격
calendar spread는 outright와 다른 상품이므로 명시적으로 제외한다. 현재 상태는
`production_transport_and_contract_verified`다.

Currencycloud adapter는 인증 → 미래일자 detailed rate → tenant-private snapshot
흐름, credential 비저장, 호출 후 session 종료 테스트를 통과했다. 2026-07-30
Demo 자격으로 USD/EUR 미래일자 quote를 실제 호출해 계약을 검증했다. Currencycloud
지원 통화에 KRW가 없으므로 이 연결은 API transport와 provider quote 계약 검증에
사용하고, USD/KRW 시장 benchmark는 KRX·ECOS가 담당한다.

credential 설정 후 실제 smoke test는 다음 명령으로 실행한다.

```powershell
$env:PYTHONPATH = "src"
python scripts/smoke_quote_apis.py krx --date 2026-07-27
python scripts/smoke_quote_apis.py currencycloud `
  --tenant-id TENANT-1 --company-id COMPANY-1 --case-id EXP-1 `
  --buy USD --sell EUR --amount 100000 --fixed-side buy `
  --conversion-date 2026-08-28
```

명령은 credential이나 원문 payload를 출력하지 않는다. KRX는 USD 선물 record
개수만, Currencycloud는 통화쌍·결제일·booking 필요 여부만 출력한다.
