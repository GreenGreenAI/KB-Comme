---
status: accepted
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-26
---

# 시스템 아키텍처 개요

TradeFlow는 도메인 모델을 중심으로 공유 계약, 지식 판정, 계산 도구와 실행
파이프라인을 분리한다.

```text
domain
  ▲
  ├── contracts
  ├── knowledge
  └── tools
         ▲
runtime ─┴── contracts + knowledge
```

- `domain`: 다른 TradeFlow 계층에 의존하지 않는 핵심 모델
- `contracts`: 계층 간 공유되는 좁은 인터페이스
- `knowledge`: 출처, 조건과 근거 기반 판정
- `tools`: 결정론적 계산과 분석
- `runtime`: 각 계층을 조립하는 최상위 파이프라인

의존 방향의 결정 근거는
[ADR-0001](../adr/0001-module-ownership-and-dependencies.md)을 따른다.
