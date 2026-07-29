---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-28
---

# ADR-0023: 사용자 진술 기반 규정 적용 관문

- 상태: 제안
- 날짜: 2026-07-28

## 배경

외국환 규정 후보를 평가하려면 거래가 상계, 제3자 지급, 상호계산 또는
외국환은행을 통하지 않는 지급에 해당하는지 먼저 알아야 한다. 이 네 사실은
공개 API가 개별 기업 거래를 대신 확인할 수 없으며, 값이 없으면 다수 규칙이
정보 부족 상태에 머문다.

그렇다고 자유 형식 대화에서 LLM이 값을 추론하거나, 사용자 진술을 공식 법령
해석과 같은 출처로 취급하면 예외 적용이나 신고 완료까지 잘못 확정할 수 있다.

## 고려한 선택지

1. 네 사실도 공식 증빙이 수집될 때까지 항상 비워 둔다.
2. 자유 형식 사용자 답변을 LLM이 모든 규정 사실로 변환한다.
3. 확인 절차를 거친 구조화된 사용자 진술을 네 개의 적용 관문에만 허용한다.

## 결정

3번을 선택한다.

- 허용 필드는 다음 네 개의 case-scoped boolean으로 제한한다.
  - `payment.is_netting`
  - `payment.is_third_party`
  - `payment.uses_mutual_account`
  - `payment.uses_foreign_exchange_bank`
- 진술에는 선언 ID, 회사 ID, 거래 ID, 선언 시각, 선언자 역할과 명시적
  `confirmed=true`가 필요하다.
- 증거 역할은 fact catalog와 동일한 `compliance`를 유지한다. 단, 출처 ID는
  `USER_DECLARATION`으로 기록하여 공식 법령·기관 자료와 구분한다.
- 진술 증거에는 `scope_gate_only`, `not_legal_interpretation`,
  `not_filing_exemption` 한계를 명시한다.
- 한 거래에는 하나의 활성 진술만 허용하며 회사·거래 범위와 미래 시각을
  fail-closed 검증한다.
- 이 경로로 예외 조항, 신고 완료, 기한 계산·위반 여부를 입력하거나 추론하지
  않는다. 관문이 `true`여도 후속 사실이 없으면 결정은 정보 부족으로 남는다.
- LLM은 진술 내용을 설명하고 누락 값을 질문할 수 있지만, 자유 문장을 임의의
  규정 fact로 변환하지 않는다.

## 결과

네 개의 적용 관문은 기업이 실제 거래 구조를 명시적으로 확인하여 제공할 수
있다. 부정 진술은 불필요한 규정 후보를 결정론적으로 제외하고, 긍정 진술은
추가 증빙·계산·전문가 확인 절차를 여는 역할만 한다.

플랫폼은 `ComplianceDeclarationAssembler`가 생성한 assertion과 evidence를 기존
case 분석 파이프라인에 합쳐야 한다. 입력 UI와 API는 이 계약을 그대로 사용하며
추가 규정 필드를 임의로 확장하지 않는다.

## 검증

- 허용 필드와 증거 역할의 catalog 일치 테스트
- 회사·거래 범위, 확인 여부, 미래 시각, 중복 활성 진술 fail-closed 테스트
- 부정 관문이 관련 규칙을 `not_eligible`로 좁히는 통합 테스트
- 긍정 관문이 예외·신고·기한을 추론하지 않고 `insufficient_information`으로
  남는 통합 테스트
- DecisionPacket에서 `USER_DECLARATION` 출처와 제한사항 보존 테스트
