---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0021: 기업 자격 증거의 비공개 스냅샷 경계

- 상태: 제안
- 날짜: 2026-07-27

## 배경

ADR-0020은 provider-neutral 자격 증거와 fact 결합 정책을 정했다. 그러나 실제
중소기업 확인·K-SURE 신용조회 응답에는 고객 식별자와 민감한 신용정보가 포함되며,
네트워크 응답을 메모리에서 바로 fact로 바꾸면 과거 판정 재현과 변조 검증이 어렵다.
또한 서로 다른 tenant가 같은 내부 거래 ID를 사용할 수 있어 case ID만으로 record를
선택하면 정보가 교차 적용될 수 있다.

## 고려한 선택지

1. 기관 API 응답을 바로 `EligibilityEvidenceRecord`로 만든다. 지연은 적지만 exact
   원문과 해시가 남지 않는다.
2. 응답을 공개 snapshot 저장소에 커밋한다. 재현은 쉽지만 고객·신용정보를 저장소에
   노출한다.
3. 인증된 connector가 normalized feed를 제공하고 공통 envelope로 비공개 snapshot을
   만든 뒤 domain parser와 runtime provider를 거친다.

## 결정

3번을 선택한다.

- dataset registry schema 1.2에 `eligibility_evidence` kind를 추가한다.
- 기업 자격과 K-SURE 신용 feed는 `runtime_private`만 허용하고 Git에서 제외한다.
- feed schema는 version, observed_at, provider key와 record 배열을 가진다.
- dataset definition과 payload의 provider key가 정확히 일치해야 한다.
- 모든 record는 `company_id`, subject kind/ID, evidence ID, 유효기한, scalar facts를
  명시한다. 회사 record는 subject ID와 company ID가 같아야 한다.
- root/record allowlist 밖의 필드는 credential 오저장을 막기 위해 거부한다.
- HTTPS adapter는 선택적 bearer token을 런타임에만 사용하며 endpoint·token을 오류나
  snapshot에 남기지 않는다.
- parser는 snapshot version·observed_at과 payload를 교차검증한다.
- runtime provider는 snapshot freshness를 다시 확인하고 현재 프로그램의 company ID와
  case ID가 모두 일치하는 record만 knowledge evidence로 변환한다.
- snapshot content hash가 record의 `EvidenceMetadata`에 들어가며, 이후 ADR-0020의
  trusted source·fact catalog·conflict·valid_until 검사를 다시 수행한다.

## 결과

실제 기관 connector의 세부 인증 방식은 교체 가능하면서 판정 입력 계약은 고정된다.
민감정보는 공개 저장소에 남지 않고, 과거 결과는 운영 비공개 snapshot의 exact hash로
감사할 수 있다. 운영 환경은 `data/runtime/` 대신 동일 보안 특성을 가진 암호화 저장소,
tenant ACL, 보존·삭제 정책을 제공해야 한다.

## 검증

- HTTPS·credential 비노출·크기 제한·safe error 테스트
- schema·중복·시간대·scope·scalar fact fail-closed 테스트
- registry parser의 version/observed_at/freshness 검사
- 같은 case ID를 가진 다른 회사 record가 제외되는 tenant 격리 테스트
- snapshot hash가 EvidenceMetadata와 FactAssembler provenance로 이어지는 통합 테스트
