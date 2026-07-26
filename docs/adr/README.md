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

## 운영 규칙

- 번호는 네 자리 연속 번호를 사용한다.
- 파일명은 `NNNN-short-kebab-title.md` 형식으로 작성한다.
- 중요한 선택지, 결정, 이유, 결과와 검증 방법을 기록한다.
- 승인된 ADR은 과거 결정의 기록이므로 의미를 바꾸지 않는다.
- 결정이 달라지면 새 ADR을 추가하고 이전 ADR을 `superseded`로 표시한다.

새 결정은 [ADR 템플릿](../templates/adr.md)으로 시작한다.
