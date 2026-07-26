---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# 데이터와 AI

## 데이터 계층

- 원문 출처와 확인 정보: `knowledge/source_registry.json`
- 실행 가능한 구조화 규칙: `knowledge/rulepacks/`
- 거래 입력과 계산 결과: 도메인 모델과 런타임 저장소
- 설명과 검토 기록: 근거 패킷을 통해 계산 결과와 연결

## AI 사용 원칙

- AI는 문서 추출, 분류, 설명 초안과 검토 보조에 사용할 수 있다.
- 금액 계산과 확정 조건 판정은 테스트 가능한 결정론적 코드가 담당한다.
- 생성된 결과에는 입력, 도구 결과, source ID와 불확실성을 남긴다.
- 확인되지 않은 생성 결과는 사람 또는 규칙 검증 전까지 확정값이 아니다.

## 출처 상태와 조건부 판정

출처의 공식성·효력기간과 스냅샷 신선성은 서로 다른 축으로 검증한 뒤
[ADR-0006](../adr/0006-source-status-and-conditional-decisions.md)의 우선순위로
합성한다. 동적 데이터는 source registry의 신원 정보와 snapshot의 버전·해시를 같은
source ID로 연결한다.

조건부 후보는 자유 문장만 반환하지 않는다. 충족해야 할 field, operator, 기대값과
현재값을 구조화해 반환하며, LLM은 이를 설명할 수 있지만 새 조건을 만들거나
정보 부족을 조건부 가능으로 승격할 수 없다.
