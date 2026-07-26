---
status: draft
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-26
---

# API 명세 원칙

API가 도입될 때 각 엔드포인트에 다음을 정의한다.

- 목적, 인증 주체와 필요한 권한
- 요청·응답 스키마와 예제
- 오류 코드, 재시도와 멱등성
- 기준일, 통화, 단위와 시간대
- 사용한 규칙·계산 버전과 근거 표현
- 호환성 및 폐기 정책

스키마에서 자동 생성할 수 있는 내용은 수기로 중복 관리하지 않는다.
