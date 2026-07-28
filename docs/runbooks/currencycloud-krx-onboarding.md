---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-28
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

2026-07-28 KRX 공식 sample endpoint에 공개 sample credential로 실제 HTTPS 요청을
보내 `OutBlock_1` 10건을 수신했다. 다만 sample은 2020-04-14 KOSPI200 선물만
반환하므로 USD 선물 parser의 운영 응답 검증은 아니다. 운영 key가 생기기 전까지
상태는 `sample_transport_verified_production_key_required`다.

Currencycloud adapter는 인증 → 미래일자 detailed rate → tenant-private snapshot
흐름과 credential 비저장 테스트를 통과했다. 실제 Demo 호출은 credential이
들어오기 전까지 `demo_credentials_required`다.

credential 설정 후 실제 smoke test는 다음 명령으로 실행한다.

```powershell
$env:PYTHONPATH = "src"
python scripts/smoke_quote_apis.py krx --date 2026-07-27
python scripts/smoke_quote_apis.py currencycloud `
  --tenant-id TENANT-1 --company-id COMPANY-1 --case-id EXP-1 `
  --buy USD --sell KRW --amount 100000 --fixed-side buy `
  --conversion-date 2026-08-28
```

명령은 credential이나 원문 payload를 출력하지 않는다. KRX는 USD 선물 record
개수만, Currencycloud는 통화쌍·결제일·booking 필요 여부만 출력한다.
