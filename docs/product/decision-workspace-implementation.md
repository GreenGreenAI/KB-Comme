---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-29
---

# Decision Workspace 구현 상태

이 문서는
[프론트엔드 보완 요구사항](decision-workspace-frontend-requirements.md)의 수용 기준과
현재 구현·검증 증거를 연결한다.

## 구현된 사용자 흐름

1. 사용자는 자연어 또는 구조화 입력으로 수출입 거래를 등록한다.
2. 결정론적 worker가 노출·환율 시나리오·지원제도·신고의무·헤지를 실행한다.
3. 한 답변 안에서 거래 타임라인, 지원제도 상태, 신고 검토, 다음 행동, 누락 정보,
   근거와 재현 hash를 확인한다.
4. 누락 정보 큐는 최대 3개를 우선 표시한다. `모름`은 `false`로 전송하지 않고
   클라이언트의 unknown 상태로 유지한다.
5. 로그인한 기업의 프로필 보완값은 인증된 전용 API에 저장되고, 분석 요청 본문은
   계정 사실을 덮어쓸 수 없다.
6. 로그인 분석은 tenant별 SQLite 이력에 저장되며 계정 메뉴에서 다시 열 수 있다.

## 응답 필드와 구현

| 응답 계약 | 컴포넌트/동작 |
|---|---|
| `company_profile` | `CompanySummary`가 실제 분석 대상 기업을 표시 |
| `trade_timeline` | `TradeTimeline` |
| `support_candidates`, `excluded_candidates` | `SupportCandidates`; 정보 부족과 조건 불충족을 구분 |
| `filing_obligations`, `risk_findings` | `ComplianceFindings`; 미실행·빈 결과·실패를 구분 |
| `next_actions` | 담당, 기한, 선행조건, 필요서류, 단계가 있는 `ActionPlan` |
| `missing_input_queue` | profile/case/compliance/hedge/external evidence 범위가 있는 우선순위 큐 |
| `review_required`, `review_reasons` | 답변 상단의 `ReviewBanner`와 행동 영역 경고 |
| `evidence`, `calculation_versions` | 공식 URL, 시점, hash, 모델·규칙·입력 fingerprint를 한 번의 펼침으로 표시 |

## 데이터 경계

- 익명 사용자는 allowlist에 포함된 기업·거래 사실만 요청에 넣을 수 있다.
- 로그인 사용자는 `/api/auth/profile`로 기업 사실을 저장한 뒤 계정에서 읽는다.
- 규정 관문 사실은 거래별 `ComplianceGatewayDeclaration`으로 만들며
  `confirmed=true`가 아니면 수용하지 않는다.
- 법적 예외, 신고 완료, 도출 기한은 사용자 선언 allowlist에 포함하지 않는다.
- 상대방 등급과 국별 인수방침처럼 외부 증거가 필요한 항목은 입력창으로 위장하지
  않고 `external_evidence`로 표시한다.

## 검증

```powershell
python -m pytest -q
cd web/frontend
npm test
npm run build
npm run test:e2e
```

- Python 테스트는 프로필·규정 선언의 DecisionPacket 도달, source metadata,
  tenant별 분석 격리를 검증한다.
- Vitest는 판정 상태, 행동 담당·기한, progressive disclosure와 unknown 처리를
  검증한다.
- Playwright 대표 흐름은 거래 입력에서 Decision Workspace, 누락 입력 패널,
  공식 근거 링크까지 확인한다.

## 의도적으로 남긴 외부 게이트

- Rulepack의 독립 도메인 전문가 승인
- 관측 선물환 이력을 이용한 모델 경제성 검증과 세 역할 승인
- 실제 신고·보험 신청·헤지 주문 실행

이 세 항목은 코드가 자동으로 대신할 수 있는 미구현 기능이 아니라 사람·기관·권한이
필요한 운영 게이트다. 시스템은 승인이나 실행을 추정하지 않고 fail-closed로 유지한다.
