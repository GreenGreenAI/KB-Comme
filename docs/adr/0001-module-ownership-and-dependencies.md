---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-26
---

# ADR-0001: 모듈 소유권과 의존 방향

- 상태: 승인
- 날짜: 2026-07-26

## 결정

의존 방향을 다음과 같이 고정한다.

```text
domain
  ▲
  ├── contracts
  ├── knowledge
  └── tools
         ▲
runtime ─┴── contracts + knowledge
```

- `domain`은 다른 TradeFlow 계층을 import하지 않는다.
- `contracts`는 `domain`만 참조한다.
- `knowledge`는 `domain`, `contracts`만 참조한다.
- `tools`는 `domain`만 참조한다.
- `runtime`은 전체를 조립하는 최상위 계층이다.

## 이유

두 담당자가 상대 모듈의 내부 구현을 수정하지 않고 병렬 작업할 수 있어야 한다.
공유 계약을 좁게 유지하면 지식 규칙과 실행 인프라가 독립적으로 발전할 수 있다.

## 검증

`tests/architecture/test_module_boundaries.py`가 금지된 역방향 import를 검사한다.
