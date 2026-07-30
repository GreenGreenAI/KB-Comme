---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# Architecture Decision Records

## 결정 목록

| ADR | 상태 | 설명 |
|---|---|---|
| [ADR-0001](0001-module-ownership-and-dependencies.md) | accepted | 모듈 소유권과 의존 방향 |
| [ADR-0002](0002-response-contract-vocabulary.md) | accepted | 응답 계약 어휘와 노출 부호 |
| [ADR-0003](0003-snapshot-contract-and-integration-leaf.md) | accepted | 스냅샷 계약의 위치와 integration 리프 |
| [ADR-0004](0004-hedge-instrument-availability-seam.md) | accepted | 헤지 수단 가용성 이음새 |
| [ADR-0005](0005-snapshot-reader-placement.md) | accepted | 스냅샷을 읽는 계층 |
| [ADR-0006](0006-source-status-and-conditional-decisions.md) | proposed | 출처 상태 합성과 조건부 판정 계약 |
| [ADR-0007](0007-llm-execution-boundary-and-decision-packet.md) | proposed | LLM 실행 경계와 DecisionPacket |
| [ADR-0008](0008-evidence-bound-case-facts.md) | proposed | 근거 결합형 케이스 fact와 규칙 오케스트레이션 |
| [ADR-0009](0009-derived-deadlines-and-action-plan.md) | proposed | 파생 기한과 결정론적 실행계획 |
| [ADR-0010](0010-decision-categories-and-action-deduplication.md) | proposed | 판정 분류와 실행계획 중복 통합 |
| [ADR-0011](0011-declarative-dataset-and-adapter-registries.md) | proposed | 선언형 데이터셋·어댑터 레지스트리 |
| [ADR-0012](0012-evidence-bound-ksure-case-orchestration.md) | proposed | 근거 결합형 K-SURE 케이스 오케스트레이션 |
| [ADR-0013](0013-bizinfo-support-program-snapshots.md) | proposed | 기업마당 지원사업 API 스냅샷 |
| [ADR-0014](0014-deterministic-collection-orchestration.md) | proposed | 결정론적 수집 주기·재시도·fallback |
| [ADR-0015](0015-snapshot-analysis-service-boundary.md) | proposed | 검증된 스냅샷 기반 분석 서비스 경계 |
| [ADR-0016](0016-fail-closed-erp-provider-mapping.md) | proposed | ERP 공급자 응답의 fail-closed 매핑 |
| [ADR-0017](0017-evidence-bound-ksure-country-policy.md) | proposed | K-SURE 국별인수방침의 스냅샷 기반 fact 파생 |
| [ADR-0018](0018-versioned-application-document-catalog.md) | proposed | 버전형 신청서류 카탈로그와 실행계획 계약 |
| [ADR-0019](0019-rulepack-promotion-and-review-policy.md) | accepted | 규칙팩 승격 게이트와 전문가 검토 정책 분리 |
| [ADR-0020](0020-subject-scoped-operational-evidence.md) | proposed | 회사·케이스 범위 운영 자격 증거와 fail-closed 결합 |
| [ADR-0021](0021-private-eligibility-evidence-snapshots.md) | proposed | 기업 자격·신용정보의 비공개 snapshot·tenant 경계 |
| [ADR-0022](0022-koreaexim-reference-fx-catalog.md) | proposed | 한국수출입은행 다통화 기준환율 catalog와 출처 역할 |
| [ADR-0023](0023-user-declared-compliance-gates.md) | proposed | 사용자 확정 진술로 규정 적용 관문만 입력하는 계약 |
| [ADR-0024](0024-user-confirmed-forward-quote-availability.md) | proposed | 사용자 확인 선물환 호가의 범위·최신성·가용성 계약 |
| [ADR-0025](0025-hedge-model-champion-challenger-governance.md) | proposed | 헤지 모델 champion/challenger 거버넌스 |
| [ADR-0026](0026-accounts-as-the-source-of-company-facts.md) | accepted | 계정은 관문이 아니라 기업 사실의 출처 |
| [ADR-0027](0027-tenant-document-and-production-security-boundary.md) | proposed | tenant 문서와 운영 보안 경계 |

## 운영 규칙

- 번호는 네 자리 연속 번호를 사용한다.
- 파일명은 `NNNN-short-kebab-title.md` 형식으로 작성한다.
- 중요한 선택지, 결정, 이유, 결과와 검증 방법을 기록한다.
- 승인된 ADR은 과거 결정의 기록이므로 의미를 바꾸지 않는다.
- 결정이 달라지면 새 ADR을 추가하고 이전 ADR을 `superseded`로 표시한다.

새 결정은 [ADR 템플릿](../templates/adr.md)으로 시작한다.
