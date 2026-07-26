---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-26
---

# 관찰 가능성

운영 단계에서 최소한 다음 신호를 구조화해 기록한다.

- 요청과 거래의 상관관계 ID
- 처리 단계, 지연 시간과 성공·실패 상태
- 계산 및 규칙 버전
- 사용한 source ID와 기준일
- 사람 검토가 필요한 사유
- 외부 연동 오류와 재시도 결과

고객 원문, 인증정보와 불필요한 개인정보는 로그에 남기지 않는다. 지표와 경보 임계값은
실제 서비스 수준 목표가 합의된 뒤 구체화한다.
