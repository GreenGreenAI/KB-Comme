---
status: proposed
owner: shared
reviewers: platform-runtime
last-reviewed: 2026-08-03
---

# Trade Deal Decision Twin UI/UX 구현 인계

## 1. 목적

이 문서는 [대회 제출 기획안](competition-proposal.md)과
[장별 발표 구성안](competition-presentation-outline.md)을 Role B의 실제 UI/UX 구현 언어로
번역한다. 기존 [Decision Workspace 프론트엔드 요구사항](decision-workspace-frontend-requirements.md)을
대체하지 않으며, 새로 정한 제품 카테고리와 대표 데모를 현재 화면에 어떻게 반영할지만 보완한다.

핵심 원칙은 다음과 같다.

> `Trade Deal Decision Twin`은 제품이 지향하는 카테고리이고,
> `Next Decisive Question → Decision Delta → Decision Passport`는 현재 구현된 대표 경험이다.

화면은 목표 카테고리를 설명할 수 있지만, 아직 구현되지 않은 계약 조항 자동 추출·위험 연쇄
전파·통합 대안 비교를 현재 기능처럼 표현해서는 안 된다.

## 2. Role B에 전달할 고정 메시지

### 2.1 한 문장

> 계약조건과 거래 사실을 날짜별 현금흐름으로 바꾸고, 결과를 바꾸는 정보를 확인해
> 변경된 결정과 금융기관 상담 준비까지 연결한다.

### 2.2 메시지 위계

| 위계 | 화면에서 전달할 내용 | 사용 위치 |
|---|---|---|
| 제품 카테고리 | Trade Deal Decision Twin | 첫 화면·소개 영역 |
| 작동 방식 | Clause-to-Cash-to-Action | 소개·데모 안내 |
| 현재 대표 경험 | Next Question → Delta → Passport | 분석 결과 영역 |
| 현재 계산 가치 | 자금 공백과 환노출을 분리해 계산 | 거래 타임라인·요약 |
| 안전 경계 | 자동 승인·접수·확정 판정이 아님 | 검토 배너·상담 인계 |

`Decision Twin`이라는 명칭 때문에 실제 계약 전체가 자동으로 디지털 트윈화됐다는 인상을
주지 않는다. 현재는 사용자가 확인한 거래 사실과 확정 결제일을 중심으로 동작한다.

## 3. 기존 화면에서 유지할 구현 기반

현재 `web/frontend/src/DecisionWorkspace.jsx`에는 다음 표현 계층이 이미 존재한다.

- `ReviewBanner`
- `DecisionDelta`
- `NextDecisiveQuestion`
- `CompanySummary`
- `TradeTimeline`
- `DocumentPanel`
- `SupportCandidates`
- `ComplianceFindings`
- `MissingInputQueue`
- `ActionPlan`
- `ConsultationHandoff`
- `CapabilityTrace`
- `EvidenceSummary`

따라서 별도 대시보드 여러 개를 새로 만드는 것이 기본 요구사항은 아니다. 자연어 대화는 입력·보완·
설명 계층으로 유지하고, 구조화된 결과를 하나의 `Decision Workspace`로 읽히게 만드는 데 집중한다.

## 4. 대표 사용자 경험

### 4.1 화면 흐름

```text
거래 입력
→ 결제일 타임라인과 현재 계산
→ 가장 영향력 있는 다음 질문
→ 사용자 답변
→ 변경된 값만 Decision Delta로 표시
→ 지원·규정·필요서류·다음 행동
→ Decision Passport 생성
→ 수동 상담 후속상태 기록
```

### 4.2 대표 수치

| 단계 | 반드시 일치해야 하는 결과 |
|---|---|
| 수입 USD 60,000 지급 + 수출 USD 100,000 수취 | 최대 자금 공백 USD 60,000 |
| 전체 경제적 상계 | 자연헤지 USD 60,000 |
| 수입 지급일까지 실제 유입된 수출대금 | 만기 대응액 USD 0 |
| 전체 잔여 환노출 | USD 40,000 |
| 보유 외화 USD 20,000 추가 | 자금 공백 USD 60,000 → USD 40,000 |

프론트가 이 값을 다시 계산하지 않는다. API가 반환한 계산값과 Delta를 그대로 표현하고,
누락되거나 상충하는 값은 클라이언트 추정으로 채우지 않는다.

### 4.3 첫 화면과 결과 화면의 역할

- 첫 화면은 서비스 정체성과 입력 예시를 짧게 전달한다.
- 결과 화면은 `현재 결과 → 결과를 바꾸는 질문 → 변경된 결과 → 다음 행동` 순으로 읽혀야 한다.
- 전체 근거와 실행 내역은 progressive disclosure로 제공한다.
- 채팅 기록을 길게 읽지 않아도 최신 결정 상태와 변경점이 식별돼야 한다.

## 5. 시각적 상태 계약

다음 상태를 색상 하나로만 구분하지 않고 배지·문구·보조 설명을 함께 사용한다.

| 시스템 상태 | 사용자 문구 | 금지 표현 |
|---|---|---|
| `eligible` | 요건 충족 | 승인 완료 |
| `conditionally_eligible` | 조건부 후보 | 신청 가능 확정 |
| `insufficient_information` | 추가 정보 필요 | 후보·제외로 임의 변환 |
| `expert_confirmation_required` | 전문가 확인 필요 | 자동 검토 완료 |
| `source_expired` | 출처 갱신 필요 | 최신 근거 |
| worker 미실행 | 실행 조건 미충족 또는 미실행 | 결과 없음 |
| 지원 범위 밖 | 현재 자동 계산 범위 밖 | 오류 또는 0으로 변환 |
| `user_recorded_not_bank_verified` | 사용자가 기록한 상담 상태 | 은행 확인·접수 완료 |

`review_required=true`이면 상단 경고와 다음 행동 영역에서 모두 확인할 수 있어야 한다.
근거가 오래됐거나 입력이 부족한 경우 결론을 약하게 표현하는 데 그치지 않고 그 이유와 다음
확인 주체를 표시한다.

## 6. 현재 기능과 목표 기능의 시각적 분리

### 6.1 현재 화면에서 실제 조작 가능한 기능

- 자연어·구조화 거래 입력
- 복합 수출입 거래 타임라인
- 자금 공백·순노출·자연헤지·만기 대응 계산
- 조건부 환율 시나리오와 fail-closed 헤지 분석
- Next Decisive Question
- Decision Delta
- 지원제도·신고 검토·필요서류·다음 행동
- Decision Passport 다운로드와 수동 상담 lifecycle
- 문서 업로드·추출·사용자 확인·불일치 검사

### 6.2 기획·발표에서만 목표 상태로 표시할 기능

- Incoterms와 상대일 결제조건 자동 추출
- 확인된 문서 사실의 거래 원장 자동 반영
- 30·60·90일 지급지연 시나리오 자동 생성
- 지급지연에서 보험·신용·금융기간까지의 자동 연쇄 전파
- 재협상·보험·채권금융·운전자금·부분헤지의 통합 비용 비교
- 실제 buyer·country·news·KB 내부 데이터 연결

목표 기능을 제품 화면에 노출해야 한다면 비활성 기능처럼 배치하지 말고 `제품 로드맵` 또는
`목표 시나리오`라는 별도 설명 영역에서만 보여준다.

## 7. 발표 화면과 실제 제품 화면의 관계

- 발표 자료의 `D+60 → D+90`은 목표 시나리오 배지를 유지한다.
- 실제 제품 캡처에는 해당 브랜치에서 재현된 값만 사용한다.
- 실제 제품에 없는 버튼·탭·은행 연계 상태를 목업으로 만들지 않는다.
- 구조 설명용 도식과 실제 UI 캡처를 같은 화면처럼 합성하지 않는다.
- 화면에 보이는 회사·거래·상담 상태는 실제 분석 요청과 저장 상태에 일치해야 한다.

## 8. Role B 수용 기준

### AC-B1 핵심 흐름

대표 복합 거래를 입력하면 타임라인, USD 60,000 자금 공백, USD 60,000 자연헤지,
USD 0 만기 대응액과 USD 40,000 잔여 환노출을 한 결과 흐름에서 확인할 수 있다.

### AC-B2 결과를 바꾸는 질문

보유 외화가 누락된 경우 `opening_balance_usd` 질문이 우선 표시되고 USD 20,000 입력 후
자금 공백 변경이 `USD 60,000 → USD 40,000`으로 나타난다.

### AC-B3 판정과 행동

지원제도·신고 검토가 실행되면 상태, 누락 정보, 근거, 검토 주체와 다음 행동이 유실되지 않는다.
worker 미실행과 후보 없음은 서로 다른 상태로 표시한다.

### AC-B4 상담 인계

Decision Passport는 자동 전송이나 은행 승인을 주장하지 않는다. 상담 lifecycle의 모든 상태는
`user_recorded_not_bank_verified` 경계를 유지한다.

### AC-B5 현재·목표 경계

실제 UI, 발표 캡처와 문서에서 `현재 구현`, `목표 기능`, `전문가 확인`, `외부 연계 필요`가
혼동되지 않는다.

### AC-B6 회귀 검증

최종 통합 커밋 하나에서 다음을 다시 실행하고 기획안의 수치를 갱신한다.

- Python 전체 회귀
- React component test
- 브라우저 E2E
- 고객 과업 benchmark
- routing acceptance
- 문서 검사

테스트 수치는 서로 다른 브랜치의 결과를 조합하지 않는다.

## 9. 현재 PR 통합 인계

2026-08-03 기준 Role B가 제안한 통합 순서는 다음과 같다.

1. [PR #61](https://github.com/GreenGreenAI/tradeflow/pull/61)의 응답·라우팅·대화 연속성 기반을
   먼저 `main`에 반영한다.
2. [PR #59](https://github.com/GreenGreenAI/tradeflow/pull/59)를 최신 `main` 위로 통합한다.
3. 겹치는 `web/app.py`, `runtime/synthesis.py`, `runtime/narration.py`, `Thread.jsx`는
   Role B의 최신 응답 계약을 유지하면서 #59의 Decision Workspace 결과 필드를 연결한다.
4. routing acceptance는 계획된 worker를, 고객 과업 benchmark는 최종 결과를 검증하므로
   둘 다 유지한다.
5. 통합된 단일 커밋에서 AC-B1부터 AC-B6까지 다시 검증한다.

이 순서는 새 UI 범위를 추가하기 위한 것이 아니라, 이미 합의된 제품 경험을 하나의 실행 가능한
트리에서 재현하기 위한 통합 절차다.

## 10. 전달 체크리스트

- [ ] 제품 카테고리와 현재 구현 범위를 분리했다.
- [ ] 대표 숫자가 API 결과와 일치한다.
- [ ] Next Question → Delta → Passport가 하나의 흐름으로 읽힌다.
- [ ] 지원·신고·근거·검토 상태가 프론트 경계에서 유실되지 않는다.
- [ ] 수동 상담 상태를 은행 확인 상태로 표현하지 않는다.
- [ ] 목표 기능은 실제 제품 기능처럼 보이지 않는다.
- [ ] 최종 통합 브랜치에서 모든 검증 수치를 다시 산출했다.
