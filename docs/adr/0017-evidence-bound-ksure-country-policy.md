---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0017: K-SURE 국별인수방침의 스냅샷 기반 fact 파생

- 상태: 제안
- 날짜: 2026-07-27

## 배경

단기수출보험 후보 규칙은 수입자가 K-SURE 국별인수방침상 인수제한국에 소재하지
않아야 한다. 기존 구현은 `counterparty.country_restricted`를 증거가 붙은 boolean으로
받았지만, 어느 시점의 어떤 국별인수방침에서 나온 값인지 시스템이 직접 재현하지
못했다.

K-Sight Country Risk Map은 공식 화면에서 정상인수국, 심층감시국, 조건부 인수국과
인수제한국을 조회하며, 화면이 사용하는 JSON 응답에는 ISO 국가코드와 상태 플래그가
포함된다. 다만 이 엔드포인트는 별도 공개 API로 문서화되지 않아 계약 변경 가능성과
재배포 조건을 고려해야 한다.

## 고려한 선택지

1. 사용자가 `country_restricted` boolean을 직접 입력한다.
   간단하지만 정책 버전과 원문 계보를 보장하지 못한다.
2. LLM이 국가명과 K-SURE 공지 검색 결과로 상태를 분류한다.
   최신성·완전성·재현성을 보장할 수 없다.
3. 공식 화면 응답을 비공개 스냅샷으로 저장하고 결정론 파서가 typed catalog와
   evidence-bound fact를 생성한다.

## 결정

세 번째 선택지를 채택한다.

1. `KsureCountryPolicyAdapter`는 K-Sight 화면의 전체 국가 응답을 하루 한 번 수집한다.
   응답 원문은 `runtime_private`에만 보관하며 48시간 freshness gate를 적용한다.
2. `KsureCountryPolicyCatalog`는 국가 디렉터리의 alpha-2 코드를 고유키로 사용한다.
   정상·조건부·인수제한·심층감시 화면 필터를 각각 조회하고 코드 집합을 디렉터리와
   교차검증한다. 여러 집합에 포함되면 인수제한, 조건부, 정상 순으로 보수적으로
   분류하고 어느 집합에도 없는 국가는 `unknown`으로 유지한다.
3. `bind_country_policy`는 거래의 `counterparty_country`로 정책을 찾고
   `counterparty.country_restricted` fact와 동일 값을 attestation하는
   `SUPPORT_ELIGIBILITY` evidence를 함께 생성한다.
4. 미등록·unknown 국가, 국가코드 누락, stale 스냅샷은 `제한 없음`으로 해석하지 않는다.
5. 조건부 인수국과 심층감시국은 인수제한국 boolean과 분리해 evidence payload에
   보존한다. 조건부 상태는 자동 승인이나 자동 제외로 사용하지 않는다.
6. 단기수출보험 후보 규칙은 K-Sight 출처와 상태 매핑 claim을 명시적으로 참조한다.

## 결과

- 국가 제한 fact가 exact snapshot version·hash·source와 함께 재현된다.
- 사용자의 임의 boolean과 LLM 국가분류를 제거할 수 있다.
- K-Sight 내부 엔드포인트 변경 시 수집·파서가 fail-closed한다.
- 공개 API 안정성과 재배포 조건이 확인되기 전까지 원문 스냅샷은 Git에 커밋하지 않는다.

## 검증

- 정상·조건부·인수제한·심층감시 상태 파싱 테스트
- 중복 국가, 잘못된 국가코드와 디렉터리에 없는 필터 결과 거부 테스트
- HTTPS·응답 크기·JSON·스냅샷 round-trip 테스트
- 미등록 국가와 기존 boolean 덮어쓰기 거부 테스트
- 스냅샷 evidence가 단기수출보험 규칙 판정과 `DecisionPacket`까지 전달되는 통합 테스트
