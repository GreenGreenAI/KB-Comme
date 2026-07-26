---
status: accepted
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-26
---

# 2인 협업 가이드

## 역할 A: 지식·도메인 담당

책임 범위:

- 무역금융·외환·신용장·보증·보험·정책자금 용어와 도메인 모델
- 공식 출처 수집, 원문 보존, 시행일과 버전 관리
- 구조화 규칙, 예외, 필요 서류와 절차 작성
- 조건 판정과 근거 패킷 테스트

주요 산출물:

- `knowledge/source_registry.json`
- `knowledge/rulepacks/*.json`
- `src/tradeflow/domain/`
- `src/tradeflow/knowledge/`
- `tests/knowledge/`

## 역할 B: 아키텍처·런타임 담당

책임 범위:

- 현금흐름, 환노출, 자금 공백과 시나리오 계산
- 분석 파이프라인, API·저장소·관측성의 기술 설계
- 성능, 오류 처리, 배포와 CI
- 계산 및 통합 테스트

주요 산출물:

- `src/tradeflow/tools/`
- `src/tradeflow/runtime/`
- `tests/platform/`
- `.github/workflows/`

## 두 역할이 만나는 지점

```text
지식·도메인 담당
  domain + knowledge
          │
          ▼
   contracts (공동 승인)
          ▲
          │
아키텍처·런타임 담당
    tools + runtime
```

공동 소유 대상은 `contracts/`, 아키텍처 경계 테스트, 최종 사용자 결과 구조입니다.
서로의 내부 구현을 직접 호출하지 않고 공유 계약을 통해 연결합니다.

## 권장 주간 흐름

1. 월요일: 이번 주 계약과 샘플 케이스 합의
2. 역할 A: 출처·규칙과 기대 판정 작성
3. 역할 B: 계산·파이프라인 구현
4. 중간 통합: 계약 테스트와 대표 케이스 실행
5. 금요일: 상호 리뷰 후 데모 시나리오 고정

초기 대표 케이스는 USD T/T 연결 거래 하나로 유지합니다. 범위를 늘릴 때는 통화,
결제방식, 상품을 동시에 늘리지 않고 한 축씩 확장합니다.
