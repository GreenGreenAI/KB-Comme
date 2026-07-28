---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# 명세 문서

- [MVP 아키텍처 설계](mvp-architecture.md)
- [API 명세 원칙](api.md)
- [공유 계약 변경 규칙](contracts.md)
- [지식 데이터 수집·구조화 계획](knowledge-data-plan.md)
- [런타임 데이터 소스와 어댑터](runtime-data-sources.md)
- [헤지 모델 검증과 승격](hedge-model-validation.md)

[MVP 아키텍처 설계](mvp-architecture.md)는 프로토타입 기간에 실제로 만들 범위와,
에이전트 계층·결정론 도구의 수학 모델을 정의한다. 코드 주석과 ADR이 참조하는 §번호는
모두 이 문서를 가리킨다. 상위 기획서는
[제품·아키텍처 기획](../product/product-architecture-plan.md)이며, 둘이 충돌하면
MVP 문서가 우선한다.

명세는 구현을 설명하는 복사본이 아니다. 실제 코드와 테스트가 검증하는 외부 동작,
호환성 규칙과 변경 절차를 기록한다.
