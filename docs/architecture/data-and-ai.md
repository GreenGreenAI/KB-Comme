---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-26
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
