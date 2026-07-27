---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-27
---

# ADR-0016: ERP 공급자 응답의 fail-closed 매핑

- 상태: 제안
- 날짜: 2026-07-27

## 배경

표준 거래피드는 방향, 미결제금액, 지급기일과 결제방식을 확정값으로 요구한다.
그러나 Business Central과 SAP의 응답 구조와 금액 의미는 서로 다르다. 공급자 필드를
이름이 비슷하다는 이유로 대체하거나 누락값을 추정하면 현금흐름과 환노출 계산 전체가
잘못될 수 있다.

특히 Business Central v2 판매송장은 `remainingAmount`를 제공하지만 구매송장은
송장 합계만 제공한다. SAP 범용 분개 항목은 AR/AP 개방 여부와 순지급기일을 안정적으로
증명하지 않으므로 Receivable Payable Item 투영이 필요하다.

## 고려한 선택지

1. 공급자 응답을 LLM으로 표준 거래피드에 직접 변환한다.
   필드 차이에 유연하지만 금액과 상태를 재현하거나 감사하기 어렵다.
2. 이름이 비슷한 필드를 기본값과 휴리스틱으로 매핑한다.
   구현은 빠르지만 송장 합계를 미결제잔액으로 오인하거나 결제방식을 추정하게 된다.
3. 공급자별 결정론 매퍼가 필요한 사실을 명시적으로 요구하고, 증명할 수 없는 응답은
   거부한다.

## 결정

세 번째 선택지를 채택한다.

1. `BusinessCentralInvoiceMapper`와 `SapReceivablePayableMapper`는 integration 리프에
   위치하며 표준 거래피드 문서만 생성한다. 계산·지식 계층은 공급자 타입을 참조하지
   않는다.
2. Business Central 판매송장은 상태가 `Open`인 `remainingAmount`만 사용한다.
   구매송장은 고객 커넥터가 원장과 대조해 추가한 `tradeflowRemainingAmount`를
   요구하며 `totalAmountIncludingTax`를 대신 사용하지 않는다.
3. SAP는 Receivable Payable Item의 고객/공급자 계정 역할, 미결제·비폐기 상태,
   거래통화 금액과 순지급기일을 모두 요구한다. 금액 부호는 명시된 계정 역할로 방향을
   정한 뒤 절댓값으로 정규화한다.
4. 결제방식은 공급자 확장 필드 또는 명시적인 고객별 기본 정책에서만 가져온다.
   `tt`를 비롯한 값을 자동 추정하지 않는다.
5. 부분 페이지, 중복 문서, JSON float 금액, 미래 수정시각, 알 수 없는 상태와 필수
   필드 누락을 거부한다. Business Central의 음수 미결제금액도 방향을 추정하지 않고
   거부한다.
6. 공급자 매퍼는 별도 운영 데이터셋을 만들지 않는다. 결과는 기존
   `ERP_TRADE_FEED_V1` 계약과 레지스트리, 스냅샷 검증 경로를 그대로 사용한다.

## 결과

- 같은 공급자 응답은 항상 같은 표준 거래피드를 만든다.
- LLM이 금액·상태·방향·결제방식을 채우는 경로가 생기지 않는다.
- Business Central 구매 잔액을 제공하는 고객별 확장 커넥터가 필요하다.
- 실제 테넌트 연결에는 OAuth, 증분 수집, 페이지 순회와 원장 필드 대조 구현이 별도로
  필요하다.

## 검증

- 판매·구매 및 고객·공급자 방향 매핑 테스트
- 합계의 잔액 대체, 음수 잔액과 결제방식 추정 거부 테스트
- OData v2/v4 부분 페이지와 중복 ID 거부 테스트
- float 금액, 미래 수정시각, 누락된 open 상태·지급기일 거부 테스트
- 생성 문서의 `parse_trade_feed_payload` 재검증

