---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-28
---

# 역할 B 런타임 연결 handoff

관련 이슈: #25

## 목적

역할 A가 제공한 사용자 규정 진술과 기업별 선물환 호가 정책을 HTTP 입력,
오케스트레이터, DecisionPacket과 응답 UI에 연결할 때 지켜야 하는 수용 계약이다.
정답 fixture는
[`runtime_wiring_cases.json`](../../knowledge/validation_suites/runtime_wiring_cases.json)에
있다.

## 요청 입력

기존 거래 입력 외에 다음 두 배열을 받는다.

- `compliance_declarations[]`
  - `declaration_id`, `company_id`, `case_id`
  - timezone-aware `declared_at`, `declared_by_role`, `confirmed`
  - `is_netting`, `is_third_party`, `uses_mutual_account`,
    `uses_foreign_exchange_bank`
- `forward_quotes[]`
  - `quote_id`, `provider_id`, `company_id`, `case_ids`
  - `base_currency`, `counter_currency`, `side`
  - Decimal 문자열 `notional`, `contract_rate`, `cost_rate`
  - `settlement_date`, timezone-aware `quoted_at`, `valid_until`, `confirmed`
- `selected_quote_id`

Pydantic의 기본 extra-field 무시는 사용할 수 없다. 오탈자나 지원하지 않는 필드는
422로 거부해야 하며 Decimal을 float로 변환하지 않는다.

## 연결 순서

1. intake가 확정한 `TradeProgram`을 만든다.
2. `ComplianceDeclarationAssembler`로 case별 assertion과 compliance evidence를
   만든다.
3. `UserQuoteHedgeAvailabilityService`로 모든 quote의 measure와 market-data
   evidence를 만든다.
4. assertion/evidence는 case rule pipeline으로, measure는 오케스트레이터의
   `hedge_measures`로 전달한다.
5. 선택된 `AVAILABLE` measure가 있을 때만 champion hedge model을 실행한다.
6. 모델 결과를 DecisionPacket 1.6 `hedge_decisions`에 넣고 정확히 하나를
   `is_champion=true`로 표시한다.
7. 응답은 사용한 quote ID, evidence ID, 모델 ID·버전과 검토 사유를 보존한다.

## 실패 계약

| 조건 | 결과 |
|---|---|
| quote 없음 | `INSUFFICIENT_INFORMATION`, 헤지 계산 금지 |
| 활성 quote가 있으나 미선택 | `CONDITIONAL`, 사용자 선택 요청 |
| 만료·범위·통화·방향·명목금액 불일치 | `UNAVAILABLE`, 헤지 계산 금지 |
| 회사·case 불일치, 미래 시각, 중복 ID | 422 fail-closed |
| 선언 미확정·미래 선언·회사 불일치 | 422 fail-closed |
| champion 계산 실패 | 다른 모델로 fallback하지 않고 정보 부족 |
| challenger만 성공 | 운영 추천으로 사용하지 않음 |

## 완료 기준

- fixture의 정상·없음·미선택·만료·회사 불일치 사례가 HTTP부터 응답까지 통과한다.
- quote와 declaration evidence가 DecisionPacket에서 손실되지 않는다.
- 만료 quote의 `contract_rate`가 존재하더라도 계산기는 호출되지 않는다.
- 같은 요청은 같은 모델 버전과 business-input fingerprint를 만든다.
- LLM은 숫자, 상태, evidence, champion 선택을 변경할 수 없다.
