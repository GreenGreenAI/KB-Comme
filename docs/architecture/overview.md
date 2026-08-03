---
status: accepted
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-26
---

# 시스템 아키텍처 개요

KB Comme는 도메인 모델을 중심으로 공유 계약, 지식 판정, 계산 도구와 실행
파이프라인을 분리한다.

```text
domain
  ▲
  ├── contracts
  ├── knowledge
  └── tools
         ▲
runtime ─┴── contracts + knowledge

integration ─→ 공개/비공개 snapshot store ─→ tools, knowledge
   (리프)              (파일)
```

- `domain`: 다른 KB Comme 계층에 의존하지 않는 핵심 모델과 계층 공통 값객체
- `contracts`: 계층 간 공유되는 좁은 인터페이스
- `knowledge`: 출처, 조건과 근거 기반 판정
- `tools`: 결정론적 계산과 분석
- `runtime`: 각 계층을 조립하는 최상위 파이프라인
- `integration`: 외부 출처 수집. 어떤 모듈도 import하지 않는 리프

`tools`가 참조할 수 있는 계층은 `domain` 하나뿐이므로, 계산 도구가 다뤄야 하는
공유 타입은 `contracts`가 아니라 `domain`에 둔다. `contracts`에는 행위 계약(Protocol)과
Runtime 전용 값객체만 남는다.

`integration`은 의존 그래프에 들어가지 않는다. 수집기는 실행되어 스냅샷 파일을 남기고,
계산과 지식 계층은 그 파일만 읽는다. 런타임 의존이 아니라 데이터 의존이므로 과거
스냅샷으로 과거 결과를 재현할 수 있고, 테스트가 외부 API 없이 실행된다.

스냅샷을 **읽는** 코드는 `domain`에 있다. 소비자가 여럿인데 그중 누구도 `integration`을
참조할 수 없으므로, 모두가 도달할 수 있는 유일한 계층에 둔다. `integration`에는 수집과
생성만 남는다.

의존 방향의 결정 근거는
[ADR-0001](../adr/0001-module-ownership-and-dependencies.md),
공유 타입의 위치와 리프 규칙은
[ADR-0003](../adr/0003-snapshot-contract-and-integration-leaf.md)을 따른다.
