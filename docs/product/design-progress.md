---
status: accepted
owner: platform-runtime
reviewers: product, knowledge-domain, bank-integration
last-reviewed: 2026-08-02
---

# 설계 프로그레스

## 1. 설계 원칙

- 금액·일자·상태 판정은 결정론적 코드가 만들고 LLM은 설명을 담당한다.
- 사실, 계산, 규칙, 출처, 버전과 검토 상태를 같은 결정 패킷에 묶는다.
- 금융기관별 연계는 핵심 도메인이 아니라 integration adapter로 둔다.
- 지원하지 않는 통화·결제방식·데이터는 추정하지 않고 fail-closed한다.
- tenant 데이터와 상담 이력은 조직 범위로 격리하고 중요한 이력은 변경 불가능하게 남긴다.

## 2. 설계 항목별 상태

| ID | 설계 항목 | 상태 | 구현된 결정 | 남은 설계 |
|---|---|---|---|---|
| D-01 | 거래·기업 도메인 모델 | 완료 | CompanyProfile, TradeCase, 거래별 case fact | 확장 결제수단의 상세 조건 |
| D-02 | 현금흐름·환노출 계산 | 완료 | 순노출, 자연헤지, 만기상계, funding gap | 다통화 유동성 정책 |
| D-03 | 근거 기반 판정 계약 | 완료 | DecisionPacket, evidence role, source status, review gate | 외부 신용증거 계약 확장 |
| D-04 | 결정 변화 경험 | 완료 | Next Decisive Question, Decision Delta, Passport | 다변수 민감도·질문 비용 모델 |
| D-05 | 계정·tenant·감사 경계 | 완료 | RBAC, session hash, tenant 조회, immutable audit | RM 교차조직 위임 모델 |
| D-06 | 문서 처리 경계 | 완료 | 암호화 저장, 추출, 사용자 확인, mismatch | L/C 조항 의미 검토 모델 |
| D-07 | 상담 lifecycle | 완료 | append-only 상태 전이, 사용자 기록 표시 | 은행 확인 서명·동의 철회·보존정책 |
| D-08 | 금융기관 provider seam | 부분 완료 | 수동 handoff provider와 중립 패킷 | 상품 catalog·자격증거·상태 provider의 실행 계약 |
| D-09 | 확장 결제방식 모델 | 예정 | 미지원 입력은 fail-closed | L/C·D/P·D/A·O/A·Usance 상태·기한 모델 |
| D-10 | 규칙팩 승격 거버넌스 | 완료 | hash 결합 검토, 3역할 승인, 원자적 승격 | 외부 승인 자체는 운영 과제 |
| D-11 | 파일럿 관측 설계 | 부분 완료 | benchmark와 감사 이벤트 존재 | 고객 과업 시간·오류·이탈 event schema |
| D-12 | 실제 은행 API 계약 | 예정 | adapter 경계와 금지사항 정의 | 인증, 멱등성, 접수 ID, callback, reconciliation |

## 3. 핵심 흐름과 책임

```text
사용자 거래·기업 사실
  → 결정론적 분석·규칙 판정
  → Next Decisive Question
  → 사용자 정보 보완·재분석
  → Decision Delta
  → Decision Passport
  → 수동 상담 lifecycle
  → 향후 Bank Adapter
```

| 경계 | 책임 | 하지 않는 일 |
|---|---|---|
| Intake | 사용자 표현을 구조화하고 불명확한 거래 확인 | 복합 거래 일부만 임의 분석 |
| Analysis | 계산·규칙·문서 근거를 재현 가능하게 생성 | LLM 문장으로 금액·자격 생성 |
| Decision Experience | 결과를 바꾸는 입력과 전후 차이 표현 | 확정되지 않은 은행 결과 주장 |
| Consultation | 동의된 패킷과 사용자 기록 이력 관리 | 자동 전송·접수·승인 추정 |
| Integration | 승인된 외부 계약을 provider로 연결 | 핵심 도메인에 KB 전용 값 고정 |

## 4. 설계 부채와 의사결정 필요사항

1. 상담 필수 정보는 분석 입력과 별도 상담 프로필 중 어디에 저장할지 결정해야 한다.
2. RM이 여러 기업을 담당할 때 조직 격리와 위임 권한 모델이 필요하다.
3. 추가자료·상담 결과의 보존기간과 삭제·철회 정책이 필요하다.
4. 결제수단 확장 전 계약일·선적일·만기일·인수일의 기준 이벤트를 표준화해야 한다.
5. 외부 신용정보는 관측시점, 동의, 허용 목적과 만료를 evidence contract에 포함해야 한다.

## 5. 설계 완료 게이트

- 새 외부 연계가 핵심 분석 모듈 변경 없이 provider로 교체 가능해야 한다.
- 같은 입력과 같은 버전은 같은 구조화 결과를 재현해야 한다.
- 미확인·만료·전문가 확인 상태가 확정 판정으로 승격되지 않아야 한다.
- 모든 tenant 조회와 변경은 조직 경계·권한·감사 검증을 통과해야 한다.
- 새 결제방식은 golden case와 fail-closed case를 함께 가져야 한다.

