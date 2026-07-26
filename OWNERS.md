# Module Ownership

실제 담당자 이름이나 GitHub 계정은 프로젝트 시작 시 역할명 옆에 기록합니다.

| 영역 | 기본 담당 | 경로 | 상대방 검토 |
|---|---|---|---|
| 공유 계약 | 공동 | `src/tradeflow/contracts/` | 필수 |
| 핵심 도메인 | 지식·도메인 담당 | `src/tradeflow/domain/` | 모델 계약 변경 시 필수 |
| 출처·규칙·근거 | 지식·도메인 담당 | `src/tradeflow/knowledge/`, `knowledge/` | production 전환 시 필수 |
| 계산 도구 | 아키텍처·런타임 담당 | `src/tradeflow/tools/` | 계산식 변경 시 필수 |
| 실행 파이프라인 | 아키텍처·런타임 담당 | `src/tradeflow/runtime/` | 외부 계약 변경 시 필수 |
| 지식 테스트 | 지식·도메인 담당 | `tests/knowledge/` | 선택 |
| 플랫폼 테스트 | 아키텍처·런타임 담당 | `tests/platform/` | 선택 |
| 경계·통합 테스트 | 공동 | `tests/architecture/` | 필수 |
| 제품·아키텍처 문서 | 공동 | `docs/` | 필수 |

## 공동 계약 변경 규칙

`contracts/` 또는 외부에 노출된 `domain/` 모델의 변경은 한 사람이 제안하고 다른
사람이 승인합니다. 구현을 먼저 바꾸지 않고 다음 순서로 진행합니다.

1. 계약과 테스트를 변경한다.
2. 양쪽 모듈의 영향 범위를 PR에 기록한다.
3. 각 구현을 계약에 맞춘다.
4. 전체 검증 명령을 통과시킨다.

