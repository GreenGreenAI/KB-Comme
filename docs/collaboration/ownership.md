---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-26
---

# 문서와 모듈 소유권

[저장소 소유권 표](../../OWNERS.md)를 기준으로 하며 문서는 다음처럼 나눈다.

| 문서 영역 | 기본 소유자 | 상대방 검토 |
|---|---|---|
| `product/` | 공동 | 필수 |
| `architecture/` | 아키텍처·런타임 | 경계·도메인 영향 시 필수 |
| `specifications/` | 공동 | 필수 |
| `operations/` | 아키텍처·런타임 | 외부 동작 영향 시 필수 |
| `collaboration/` | 공동 | 필수 |
| `adr/` | 제안자 | 승인 전 상대 담당자 필수 |

`.github/CODEOWNERS`는 병합에 필요한 실제 GitHub 리뷰어를 지정한다. 역할이나
담당자가 바뀌면 소유권 표와 CODEOWNERS를 같은 PR에서 갱신한다.
