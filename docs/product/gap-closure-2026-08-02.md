---
status: accepted
owner: product-platform
reviewers: knowledge-domain, bank-integration
last-reviewed: 2026-08-02
---

# 제품 공백 해소 추적 — 2026-08-02

## 이번 차수에서 닫은 공백

| 공백 | 구현 | 검증 |
|---|---|---|
| 상담 패킷 이후 후속 흐름 부재 | `전달 준비 → 수동 전달 → 상담 중 → 추가자료 요청 → 결과 기록`을 append-only 이벤트로 저장 | tenant 격리·잘못된 전이 거부 테스트, UT17, Playwright |
| 상담 결과가 은행 확정처럼 보일 위험 | 모든 후속 상태에 `user_recorded_not_bank_verified`를 명시하고 자동 접수·승인을 주장하지 않음 | API·UI·벤치마크 검증 |
| 상담자료 완성도 불명확 | 업로드 문서 inventory와 상담 전 누락·미확인 항목을 패킷 1.1에 구조화 | handoff 통합 테스트, UT17 |
| 후속 흐름 회귀 검증 부재 | 실제 ASGI API와 브라우저 경로를 각각 자동화 | 고객 과업 17/17, 구조화 검증 58/58, E2E 4/4 |

상담자료의 `missing_or_unverified`는 실제 데이터가 확보됐다는 뜻이 아니라, 다음 네 영역을
명시적으로 수집·확인해야 한다는 계약이다: 희망 한도, 과거 무역실적, 거래상대방 신용 근거,
은행 상품 취급·한도·승인. 연결 문서가 없으면 업로드 문서 부재도 별도로 표시한다.

## 계속 남는 공백

| 우선순위 | 공백 | 현재 안전 경계 | 완료 조건 |
|---|---|---|---|
| 출시 차단 | K-SURE·외국환 규칙팩 독립 도메인 전문가 승인 | `draft`, `production_ready=false` 유지 | 독립 검토 증거 기록과 승격 게이트 통과 |
| 출시 차단 | 실제 고객·RM 파일럿 | 자동화 벤치마크 결과만 효용 근거로 사용 | 대표 고객과 RM의 과업 성공·이해도·상담자료 유용성 측정 |
| P1 | KB 상품·접수 API | 수동 패킷, `transmission_performed=false` | 공식 계약·인증·sandbox·접수 ID·멱등성 확보 |
| P1 | 희망 한도·무역실적·상대방 신용 실제 데이터 | 패킷에서 미확인으로 노출 | 사용자 입력 계약 또는 권한 있는 provider 연결 |
| P1 | L/C, D/P, D/A, O/A, Payment Usance | 지원 범위 밖이면 fail-closed | 결제수단별 모델·규칙·golden case·전문가 승인 |
| P2 | 상담 운영 고도화 | 사용자 기록만 저장 | RM 배정, 권한 분리, 은행 확인 서명, 동의 철회·보존정책 |
| P2 | Capability 4개 | `support_policy_finance`, `lc_review`, `country_risk`, `buyer_credit` 미지원 표시 | 각 capability의 데이터 계약·판정·검증 세트 구현 |

이번 구현은 상담 후속조치 공백을 닫았지만, 외부 승인이나 실제 은행 결정을 대체하지 않는다.
