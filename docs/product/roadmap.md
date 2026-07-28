---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-29
---

# 제품 로드맵

| 단계 | 목표 | 완료 기준 | 현재 상태 |
|---|---|---|---|
| Phase 0 | 업무·데이터 정의 | 대상 거래, 용어, 출처와 기본 결과 합의 | 완료 |
| Phase 1 | 거래·계산 기반 | 현금흐름·순노출 계산과 회귀 테스트 | 완료 |
| Phase 2 | 금융지원·규정 탐색 | 공식 출처 기반 후보·신고 판정, 근거 패킷 | 구현 완료, 독립 전문가 승인 대기 |
| Phase 3 | 실행·검토 Workspace | 기업·RM 검토 흐름, 행동계획, 감사 기록, tenant 이력 | MVP 구현 완료 |
| Phase 4 | 문서·신용장 | 문서 추출, 신용장 조건·불일치 분석 | 후속 |
| Phase 5 | 외부 실행 연동 | 승인된 시스템별 안전한 제출·주문 통합 | 후속 |

## 현재 Phase의 종료 조건

Phase 2–3의 코드 종료 조건은 충족됐다.

- 결정론적 노출·시장·지원·규정·헤지 흐름
- DecisionPacket과 LLM 합성 경계
- 기업 사실과 거래별 규정 선언 입력 계약
- Decision Workspace와 누락 정보 큐
- 공식 출처·버전·hash·검토 사유 표시
- 계정·세션·기업 프로필·tenant별 분석 이력
- 모델 검증 결과 영속화와 3역할 승격 workflow
- Python, React component, production build, 대표 browser E2E

운영 종료 조건 중 다음은 외부 권한이 필요하다.

- 규정·지원 Rulepack의 독립 도메인 전문가 승인
- 실제 관측 선물환 이력에 대한 모델 검증과 3역할 승인
- 실제 신고·보험·헤지 실행 시스템의 계약과 권한

외부 승인을 받기 전까지 시스템은 `production_ready`나 모델 champion 변경을
허용하지 않는다. 승인 대기는 미확정 상태로 표시하며, 자동 실행 범위를 넓히지 않는다.

단계의 범위와 우선순위를 바꾸는 PR은 변경 이유, 성공 지표와 영향받는 단계를 함께
기록한다. 상세 백로그는 이 문서가 아니라 이슈 트래커에서 관리한다.
