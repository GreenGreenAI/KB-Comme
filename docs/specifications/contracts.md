---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-26
---

# 공유 계약 변경 규칙

`contracts/` 또는 외부에 노출된 `domain/` 모델 변경은 다음 순서를 따른다.

1. 사용 사례와 호환성 영향을 문서화한다.
2. 계약과 기대 동작을 나타내는 테스트를 먼저 변경한다.
3. 지식·도메인과 플랫폼·런타임 양쪽 영향을 PR에 기록한다.
4. 각 구현을 새 계약에 맞춘다.
5. 상대 담당자 승인과 전체 검증을 완료한다.

호환되지 않는 변경은 마이그레이션 또는 명시적인 버전 전략 없이 병합하지 않는다.
