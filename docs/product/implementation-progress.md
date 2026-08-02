---
status: accepted
owner: platform-runtime
reviewers: product, knowledge-domain
last-reviewed: 2026-08-02
---

# 구현 프로그레스

## 1. 구현 기준선

이 문서는 코드가 실제로 제공하는 기능만 추적한다. 기획 문구나 설계 문서만 있고 실행 경로와
검증이 없으면 완료로 표시하지 않는다.

## 2. 기능별 상태

| ID | 구현 영역 | 상태 | 현재 구현 | 직접 검증 | 다음 작업 |
|---|---|---|---|---|---|
| I-01 | 현금흐름·환노출 | 완료 | funding gap, 순노출, 자연헤지, 만기상계 | 계산·경계값 테스트, UT02·06·07 | 다통화 확장 |
| I-02 | 거래 intake | 완료 | 단일·복합 거래 확인, 미지원 범위 거절 | UT01·04·09~14 | 확장 결제수단 parser |
| I-03 | 금융지원·규정 | 부분 완료 | K-SURE 후보와 외국환 규정, 근거·누락 상태 | validation suite와 회귀 테스트 | 독립 전문가 승인 |
| I-04 | 환율 시나리오·헤지 | 완료 | 공식 snapshot, 사용자 확인 호가, 손익 하한 비율 | UT15와 모델 검증 | 실제 호가 이력 검증 |
| I-05 | Decision Workspace | 완료 | 결과·근거·누락정보·행동계획 화면 | React와 Playwright | pilot UX 개선 |
| I-06 | 문서 Workspace | 완료 | 암호화 업로드, 추출, 확인, 정합성 검사 | runtime·API·React·E2E | L/C 의미 검토 |
| I-07 | 차별화 workflow | 완료 | Next Question, Delta, Passport | UT16과 계약 테스트 | 다변수 변화 분석 |
| I-08 | 상담 후속조치 | 완료 | 수동 전달·상담·추가자료·결과의 immutable 이력 | UT17, tenant·전이 테스트, E2E | RM 배정·은행 확인 상태 |
| I-09 | 계정·보안·감사 | 완료 | RBAC, session, 조직 격리, hash-chain audit | SQLite·보안 테스트 | 운영 key·retention 점검 |
| I-10 | 운영 저장소 | 완료 | SQLite 개발, PostgreSQL 운영 store | PostgreSQL CI 통합 테스트 | migration 운영 절차 |
| I-11 | 결제수단 확장 | 예정 | 미지원 범위 fail-closed | 거절 시나리오 | L/C·D/P·D/A·O/A·Usance |
| I-12 | 외부 위험·신용정보 | 예정 | provider 미연결 상태 표시 | capability acceptance | country/buyer evidence provider |
| I-13 | KB 실제 연계 | 예정 | 수동 패킷, 자동 전송 false | handoff 안전성 테스트 | 공식 API 확보 후 adapter |
| I-14 | 실제 사용자 검증 | 차단 | 자동화 benchmark만 완료 | 17/17, 58/58 | 고객·RM 파일럿 실행 |
| I-15 | 전체 capability | 부분 완료 | 18/22 충족 | acceptance harness | 4개 미지원 capability |

## 3. 미지원 capability

| Capability | 현재 상태 | 선행조건 |
|---|---|---|
| `support_policy_finance` | 미지원 | 정책금융 상품·대상·시점 데이터 계약 |
| `lc_review` | 미지원 | UCP600 기반 조항 모델과 전문가 검증 |
| `country_risk` | 미지원 | 권한 있는 국별 위험 snapshot provider |
| `buyer_credit` | 미지원 | 거래상대방 식별·동의·신용증거 provider |

## 4. 출시 게이트

### 코드·검증 게이트

- [x] 지원 범위 내 결정론적 계산 회귀
- [x] 복합 거래와 미지원 범위 fail-closed
- [x] tenant 격리, 감사와 상담 이력 무결성
- [x] 브라우저부터 API·저장·응답까지 대표 E2E
- [x] 상담자료 자동 전송·은행 승인 오인 방지

### 외부 운영 게이트

- [ ] K-SURE 규칙팩 독립 도메인 전문가 승인
- [ ] 외국환 규칙팩 독립 도메인 전문가 승인
- [ ] 실제 고객·RM 파일럿 합격
- [ ] 운영 개인정보·동의·보존정책 검토
- [ ] 실제 금융기관 연계 시 보안·계약·sandbox 검증

## 5. 현재 검증 결과

| 명령·검증 | 결과 |
|---|---:|
| `python -m pytest -q` | 676 passed, 2 skipped |
| `npm test` | 23 passed |
| `npm run test:e2e` | 4 passed |
| `npm run build` | passed |
| `python scripts/benchmark_user_tasks.py --json` | 17/17 tasks, 58/58 checks |
| `python scripts/check_docs.py` | 73 files passed |

## 6. 다음 구현 순서

1. 상담 희망 한도·무역실적·거래상대방 신용 근거의 입력·저장 계약
2. 파일럿 관측 event와 결과 export
3. `country_risk`와 `buyer_credit`의 provider skeleton
4. 고객 증거가 확보된 결제수단부터 하나씩 확장
5. 실제 KB 계약 확보 후에만 live adapter 구현
