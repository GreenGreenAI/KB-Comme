---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0018: 버전형 신청서류 카탈로그와 실행계획 계약

- 상태: 제안
- 날짜: 2026-07-27

## 배경

규칙의 `required_documents` 문자열 목록은 출처·버전·신청단계를 식별하지 못하고,
조건부 서류와 거래유형별 택일 청약서를 모두 필수처럼 보이게 할 수 있다. 자격조건을
잘 판정하더라도 잘못된 서류 안내는 신청 업무를 방해하므로 실행계획까지 결정론적
구조가 필요하다.

## 고려한 선택지

1. 기존 문자열 목록에 출처만 추가한다. 변경은 작지만 조건부·택일 의미가 사라진다.
2. 규칙마다 구조화 서류를 복사한다. 실행은 쉽지만 상품별 서류 변경이 여러 규칙에
   중복되어 버전 불일치가 생긴다.
3. 버전형 document set을 별도 관리하고 규칙은 ID로 참조한다. 계약 변경이 필요하지만
   출처·버전·조건과 재사용 경계가 명확하다.

## 결정

선택지 3을 채택한다.

- `knowledge/document_catalogs`에 상품·단계·버전·source/claim을 가진 세트를 둔다.
- 요구 그룹은 `required`, `conditional`, `one_of` 중 하나다.
- `one_of`는 두 개 이상의 선택지와 `selector_field`가 필요하다.
- 규칙은 inline `required_documents`와 `document_set_ids`를 동시에 사용하지 않는다.
- 실행계획의 평탄한 `required_documents`에는 `required`만 포함한다.
- `DecisionPacket` 1.5는 세트 ID와 구조화 요구 그룹을 변경 불가능한 값으로 전달한다.
- document set의 공식 출처도 규칙의 source/claim 계보와 최신성 게이트에 포함한다.

## 결과

LLM과 UI는 조건부·택일 서류를 오표시하지 않고 공식 근거와 버전을 제시할 수 있다.
거래유형이나 기업형태 fact가 없는 경우 특정 서류를 임의 선택하지 않는다. 기존
규칙팩의 inline 문자열은 호환을 위해 유지하지만, catalog를 참조하는 규칙에서는
혼용을 금지한다.

## 검증

- catalog schema·중복·요구 그룹 불변식 테스트
- 규칙과 document set 상품 ID·참조 무결성 테스트
- K-SURE 케이스에서 document set/source/claim이 action과 packet까지 전달되는 테스트
- 공식 신청서류 페이지 marker 감시와 extract canonical hash 검증
