---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-28
---

# Decision Workspace 프론트엔드 보완 요구사항

## 1. 목적

이 문서는 `origin/main`의 `f130a52`를 기준으로 실제 브라우저에서 TradeFlow
프론트엔드를 검토한 결과와 후속 수용 기준을 정의한다.

현재 화면은 자연어 거래 입력, 환노출·자금공백·자연헤지 계산과 환율 시나리오를
대화 안에서 이해하기 쉽게 보여준다. 그러나 백엔드가 이미 생성하는 지원제도,
신고의무, 필요서류, 다음 행동, 검토 상태와 근거를 사용자에게 전달하지 못한다.

따라서 현재 상태는 다음과 같이 정의한다.

> **대화형 FX 현금흐름 분석 프로토타입은 성립하지만, 거래별 실행계획을 제공하는
> Trade Decision OS의 Decision Workspace는 아직 완성되지 않았다.**

이 PR은 Role B가 소유한 프론트 구현을 직접 변경하지 않는다. 제품 계약과 이미
존재하는 API 필드를 화면에 연결하기 위한 요구사항만 확정한다.

## 2. 검토 기준

다음 문서를 제품 기준으로 사용했다.

- [제품 비전과 범위](vision-and-scope.md)
- [사용자 흐름](user-flows.md)
- [제품 로드맵](roadmap.md)
- [MVP 아키텍처](../specifications/mvp-architecture.md)
- [공유 응답 계약](../specifications/contracts.md)

대표 흐름은 다음 순서로 브라우저에서 실행했다.

1. `10월 24일에 수출대금 10만 달러 받기로 했어요`
2. 기준 영업이익 `6,000,000원`, 목표 손익 하한 `4,000,000원`
3. `8월 25일에 수입대금 6만 달러도 나가요`

확인된 결과는 다음과 같다.

- 순노출: USD 100,000 → USD 40,000
- 자연헤지: USD 60,000
- 지급이 수취보다 먼저 발생해 자금공백 USD 60,000
- 만기 대응액 0을 별도 문장으로 설명
- 실제 호가가 없어 헤지비율 계산을 fail-closed로 중단
- ECOS snapshot과 변동성 시나리오 표시

## 3. 현재 의도에 맞게 구현된 부분

다음 항목은 유지해야 한다.

### 3.1 대화와 구조화 입력의 결합

- 사용자는 거래를 자연어로 시작할 수 있다.
- 금액과 목표이익처럼 정확성이 필요한 값은 구조화 입력으로 보완한다.
- 새 거래인지 기존 거래 수정인지 모호하면 추측하지 않고 확인한다.

### 3.2 결정론적 계산의 시각화

- 순노출, 자금공백, 자연헤지를 한 카드에서 비교한다.
- 환율 범위를 확정 예측이 아니라 조건부 시나리오로 표현한다.
- 관측기간, 신뢰수준, 변동성과 `drift=0` 가정을 함께 표시한다.
- 실행된 worker를 단계별로 보여준다.

### 3.3 Fail-closed

- 확인된 선물환 호가가 없을 때 임의의 헤지비율을 생성하지 않는다.
- 필요한 입력을 사용자가 정하기 전 목표 손익 하한을 추정하지 않는다.
- 실행되지 않은 영역은 이유를 표시한다.

## 4. 해결해야 할 핵심 격차

### P1. 완료된 지원제도·신고 판정이 화면에서 사라진다

`Thread.jsx`는 `hedge_analysis` 또는 `workers.skipped` 사유만 렌더링한다.
지원 또는 compliance worker가 완료되면 skipped 사유가 없으므로 해당 섹션은
`null`이 된다.

그 결과 API에 다음 값이 존재해도 화면에 나타나지 않는다.

- `support_candidates`
- `excluded_candidates`
- `filing_obligations`
- `required_documents`
- `next_actions`

#### 요구사항

- support worker가 완료되면 후보, 조건부 후보, 제외 후보를 각각 표시한다.
- 후보마다 상품명, 상태, 포함·제외 이유, 누락 정보와 source ID를 표시한다.
- compliance worker가 완료되면 신고 검토사항, 기관, 조건, 기한과 누락 사실을
  표시한다.
- 비어 있는 배열과 worker 미실행을 같은 상태로 표현하지 않는다.

### P1. 후속 입력 수집이 hedge에만 연결돼 있다

현재 `AskBar`는 `required_inputs.hedge`만 소비한다. 지원제도와 신고 판정에 필요한
기업·거래구조·상대방 정보는 `missing_information`에 남지만 구조화된 보완 경로가
없다.

#### 요구사항

- worker별 누락 입력을 하나의 우선순위 큐로 통합한다.
- 질문은 한 번에 최대 3개로 제한한다.
- 다음 결과를 실제로 열 수 있는 입력을 먼저 질문한다.
- 입력은 `profile`, `case`, `compliance declaration`, `hedge quote` 범위로
  구분해 올바른 계약에 저장한다.
- 사용자가 “모름”을 선택하면 `false`로 변환하지 않고 `unknown`을 유지한다.

### P1. 표시된 기업 프로필과 실제 분석 입력이 다르다

상단 계정 메뉴는 `한빛정밀`, `중소기업`, `제조업`과 저장된 기업 정보가 있다고
표시한다. 그러나 `App`의 profile은 빈 객체로 시작하며 `Nav`에서 어떠한 값도
전달받지 않는다.

사용자는 저장 정보가 판정에 반영됐다고 생각하지만 API는 `company_name`,
`is_sme`, 업종 등을 받지 못한다.

#### 요구사항

둘 중 하나를 선택한다.

1. 데모 프로필을 실제 분석 state에 주입하고 요청·결과에 `demo`임을 표시한다.
2. 실제 인증·프로필 연결 전에는 로그인·저장 상태를 제거하고 명확한
   `데모 데이터` 배지를 표시한다.

화면에 표시한 기업 사실과 `DecisionPacket.inputs`는 반드시 일치해야 한다.

### P1. 최종 결과가 실행계획으로 끝나지 않는다

TradeFlow의 최종 산출물은 분석 수치가 아니라 담당자가 수행할 거래별
`Trade Decision Plan`이다. 현재 화면은 다음 API 필드를 사용하지 않는다.

- `required_documents`
- `next_actions`
- `review_required`
- `review_reasons`
- `missing_information`

#### 요구사항

답변 카드 마지막에 다음 행동 영역을 둔다.

| 필드 | 화면 표현 |
|---|---|
| 행동 | 사용자가 해야 할 구체적인 동사형 작업 |
| 담당 | 기업 담당자, 은행 RM, 외환은행, K-SURE 등 |
| 기한 | 법정·상품·내부 기한을 구분 |
| 선행조건 | 완료 전에 필요한 사실이나 승인 |
| 필요서류 | 필수, 조건부, 하나 이상 선택 그룹 구분 |
| 검토 상태 | 자동 확정이 아닌 이유와 검토 주체 |

### P2. 근거 패널이 감사 계약을 충분히 표시하지 않는다

현재 근거 패널은 snapshot의 `source_id`와 `version`만 표시한다. 제품이 약속한
“입력, 계산식, 출처와 불확실성”을 검토하기에는 부족하다.

#### 요구사항

근거 상세에 다음을 연결한다.

- source ID, 공식 출처명과 URL
- 관측·수집·시행·만료 시점
- snapshot version과 content hash
- formula/model/rulepack 버전
- 적용된 조건과 판정 이유
- 입력 fingerprint 또는 재현 식별자
- `review_required`와 사유
- source expired, insufficient information, expert confirmation 상태

사용자가 처음부터 hash를 읽게 할 필요는 없다. 요약 → 판정 이유 → 재현 상세의
progressive disclosure를 사용한다.

### P2. 데모용 인증·저장이 실제 기능처럼 보인다

현재 README는 인증과 저장이 없다고 명시하지만 계정 메뉴는 다음을 실제 상태처럼
표시한다.

- 저장한 분석 4건
- 기업 정보 3개 항목 저장됨
- 근거 이력 snapshot 12건

#### 요구사항

- 실제 데이터가 아니면 숫자를 제거하거나 `데모`임을 명시한다.
- `href="#"` 링크를 실제 탐색 링크처럼 제공하지 않는다.
- 구현되지 않은 영역은 disabled 상태와 준비 중 설명을 사용한다.

### P2. 재계산마다 전체 결과 카드가 반복된다

손익 정보를 입력하거나 거래를 하나 추가하면 이전 결과 아래에 전체 카드가 다시
쌓인다. 변경 이력을 대화로 남기는 장점은 있지만 긴 거래에서는 사용자가 무엇이
달라졌는지 비교하기 어렵다.

#### 요구사항

- 새 카드에는 변경된 값과 새로 열린 영역을 우선 표시한다.
- “순노출 USD 100,000 → USD 40,000”처럼 이전 값과 새 값을 비교한다.
- 전체 결과는 펼쳐서 볼 수 있게 하되 기본 상태에서는 변경 요약을 제공한다.

## 5. 목표 화면 구조

채팅을 없애는 것이 목표가 아니다. 채팅은 진입·보완·설명 계층으로 유지하고,
답변 안에 구조화된 Decision Workspace를 구성한다.

```text
사용자 질문
  └─ TradeFlow 설명
      ├─ 1. 현재 상태
      │    ├─ 거래 타임라인
      │    ├─ 순노출
      │    ├─ 자연헤지·만기 대응
      │    └─ 자금공백
      ├─ 2. 시장·헤지
      │    ├─ 조건부 환율 범위
      │    ├─ 손익분기
      │    └─ 무헤지·권장·100% 비교
      ├─ 3. 지원제도
      │    ├─ 후보
      │    ├─ 제외 이유
      │    └─ 필요서류
      ├─ 4. 신고의무
      │    ├─ 검토 항목
      │    ├─ 기관·기한
      │    └─ 추가 확인 사실
      ├─ 5. 다음 행동
      │    ├─ 담당자
      │    ├─ 마감일
      │    └─ 선행조건
      └─ 6. 근거와 재현
           ├─ 출처·시행일
           ├─ 공식·모델·규칙 버전
           └─ 검토 필요 사유
```

## 6. 응답 필드와 컴포넌트 매핑

| API 필드 | 권장 컴포넌트 | 빈 값 처리 |
|---|---|---|
| `trade_timeline` | `TradeTimeline` | 거래 입력 요청 |
| `cashflow_analysis` | `ExposureSummary` | 계산 중단 사유 |
| `market_scenario` | `RateScenario` | 데이터 상태 표시 |
| `hedge_analysis` | `HedgeComparison` | quote/목표 누락 구분 |
| `support_candidates` | `SupportCandidates` | 후보 없음과 미판정 구분 |
| `excluded_candidates` | `ExcludedCandidates` | 접힌 상태 허용 |
| `filing_obligations` | `ComplianceFindings` | 신고 불필요 확정과 미판정 구분 |
| `required_documents` | `DocumentChecklist` | 조건부 그룹 유지 |
| `next_actions` | `ActionPlan` | 행동 없음의 이유 표시 |
| `missing_information` | `MissingInputQueue` | `unknown` 유지 |
| `evidence` | `EvidenceSummary` | 근거 부족 경고 |
| `review_required` | `ReviewBanner` | 사유와 검토자 표시 |
| `calculation_versions` | `ReproducibilityDetail` | 개발자 상세로 접기 |

## 7. 수용 기준

### AC-1 지원제도

기업 사실을 충족한 fixture에서 support worker가 완료되면 최소 한 개의 후보 카드가
표시되고, 상품명·상태·이유·source ID를 확인할 수 있다.

### AC-2 신고의무

제3자 지급 또는 상계 선언 fixture에서 신고 검토 결과가 기관·근거·누락 사실과
함께 표시된다. 누락 사실이 있으면 “신고 불필요”로 표현하지 않는다.

### AC-3 실행계획

`next_actions`가 있는 응답은 담당자·기한·필요서류를 포함한 행동 목록으로 끝난다.
`review_required=true`이면 답변 상단과 행동 영역 모두에 검토 필요 상태가 나타난다.

### AC-4 프로필 일치

화면에 표시된 회사명과 중소기업 여부가 실제 `/api/analyze` 요청 및
`DecisionPacket.inputs`와 일치한다.

### AC-5 근거

사용자는 하나의 판정에서 공식 출처, 규칙 또는 모델 버전, 효력·최신성, 판정 이유를
최대 두 번의 펼침 동작으로 확인할 수 있다.

### AC-6 상태 구분

다음 상태를 같은 문구로 합치지 않는다.

- 실행 결과 없음
- worker 미실행
- 입력 부족
- source 만료
- 전문가 확인 필요
- 조건 불충족
- 실제 후보 없음

### AC-7 회귀

기존 대표 흐름은 그대로 동작한다.

- 단일 수출 거래의 순노출과 환율 밴드
- 수출·수입 결합 시 자연헤지와 자금공백
- 만기 불일치 설명
- 실제 선물환 호가가 없을 때 fail-closed
- 모호한 거래 추가·수정 확인

## 8. 권장 구현 순서

1. `support_candidates`, `filing_obligations`, `next_actions` 렌더링
2. 프로필 표시와 실제 분석 state 일치
3. 전체 missing-information 질문 큐
4. 근거·검토 상태 progressive disclosure
5. 변경 요약과 전체 결과 카드 반복 축소
6. 컴포넌트·접근성·대표 사용자 흐름 테스트

## 9. 범위 밖

이 요구사항은 다음 작업을 승인하지 않는다.

- 실제 금융상품 주문
- 외환 신고 자동 제출
- K-SURE 신청 자동 제출
- 임시 인증 화면을 실제 인증으로 간주
- LLM을 이용한 금액 재계산 또는 규정 재판정

실행은 계속 사람과 권한 있는 외부 시스템의 책임으로 남는다.
