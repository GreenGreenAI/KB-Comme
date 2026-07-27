---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0020: 주체 범위가 있는 운영 자격 증거

- 상태: 제안
- 날짜: 2026-07-27

## 배경

`FactCatalog`와 `FactAssembler`는 규칙 입력의 형식과 evidence role을 검증하지만,
기업 규모·신용상태·K-SURE 등급을 취득하는 adapter가 공통 객체 없이 값과 evidence
ID를 직접 만들면 세 가지 문제가 생긴다. 회사 사실이 다른 회사나 거래에 적용될 수
있고, 오래된 조회 결과가 현재 사실처럼 사용될 수 있으며, 복수 출처가 충돌할 때
호출 순서가 사실상 우선순위가 될 수 있다.

## 고려한 선택지

1. API 응답을 각 케이스의 자유형 attributes로 복사한다. 구현은 짧지만 출처와
   유효기한을 잃고 core fact 우회 경로가 생긴다.
2. source별 adapter가 `FactAssertion`을 직접 생성한다. 형식은 맞지만 adapter마다
   주체 범위·충돌·stale 정책을 반복한다.
3. provider-neutral evidence record를 먼저 만들고 하나의 assembler가 fact 입력으로
   승격한다. 객체가 하나 더 생기지만 정책과 테스트 경계가 고정된다.

## 결정

3번을 선택한다.

- provider는 `EligibilityEvidenceProvider` 계약으로 등록하며 provider key를 중복할
  수 없다.
- 응답은 회사 또는 거래 케이스 중 하나의 `subject_kind/subject_id`에 귀속한다.
- 모든 record는 신뢰된 source ID, 관측·취득·유효기한, canonical SHA-256을 가진다.
- 기업 규모·신용 제한 여부는 `CompanyQualificationEvidence`, K-SURE 수출자·수입자
  등급은 `KsureCreditEvidence` 타입으로 표현한다.
- assembler는 fact catalog에 없는 field, 잘못된 evidence role, 미래 시각, 신뢰되지
  않은 source, 잘못된 주체를 거부한다.
- 같은 field의 복수 fresh 값이 다르면 임의 우선순위를 적용하지 않고 실패한다.
- stale record는 assertion을 만들지 않는다. 감사용 `unusable_evidence`에는 남지만
  `facts` attestation과 evidence coverage에는 포함하지 않는다.
- `EligibilityFactInput`은 결정론 파이프라인의 전용 진입점으로 전달되며 LLM은 이
  과정에 개입하지 않는다.

## 결과

운영 adapter가 달라도 규칙 엔진에 도달하는 증거 계약과 실패 동작은 동일해진다.
회사 범위 사실은 해당 회사의 모든 케이스에만 적용되고 수입자 등급은 한 케이스에만
적용된다. 실제 중소기업 확인과 K-SURE 조회 adapter는 인증·이용약관을 확인한 뒤 이
provider 계약을 구현해야 한다.

## 검증

- 회사/케이스 scope 투영 및 실제 K-SURE 파이프라인 통합 테스트
- 동일값 다중 출처의 provenance 보존과 상충값 거부 테스트
- stale·future·untrusted·잘못된 role·잘못된 주체 거부 테스트
- stale/rejected descriptor가 evidence coverage를 충족하지 않는 회귀 테스트
