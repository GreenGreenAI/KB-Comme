---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime, domain-expert
last-reviewed: 2026-07-28
---

# 규정 독립 검토 및 FXall 실호가 온보딩

## 1. 규정 검토

Tradeflow 작성자가 자신의 규칙을 `domain_expert`로 승인해서는 안 된다.
`scripts/build_rulepack_review_packets.py`가 만드는 패킷은 규칙·golden case·경계값과
각 원본의 canonical SHA-256을 한 묶음으로 고정한다.

- `FX_COMPLIANCE_MVP`: 한국은행 외환심사팀에 조건, 예외, 신고기관, 신고시점,
  서류와 경계값을 질의한다.
- `KSURE_MVP_CANDIDATES`: 한국무역보험공사 고객센터/상품 담당자에게 대상기업,
  대상거래, 결제기간, 신청서류와 후보 판정을 질의한다.
- 답변자는 규칙 작성자와 독립적이어야 하며 이름, 소속, 답변일, 전문성 또는
  기관 권한 근거가 남아야 한다.
- 답변은 검토한 `rulepack_hash`와 `validation_suite_hash`를 반드시 가리킨다.
  규칙이나 suite가 바뀌면 이전 답변은 자동으로 stale이다.
- 답변 전까지 규칙은 `draft`, `production_ready=false`,
  `expert_confirmation_required`를 유지한다.

공식 접점:

- 한국은행 외환심사팀: 02-759-5300, 외환거래 심사 및 온라인 신고 안내
- 한국무역보험공사 고객센터: 1588-3884, 환변동보험 등 상품 상담

개별 기업 사실관계에 대한 공식 답변 원문에는 개인정보·거래정보가 포함될 수
있으므로 저장소에 넣지 않는다. 저장소에는 비식별 검토 결과와 원문 증빙의
tenant-private 해시만 둔다.

## 2. FXall 실호가

우선 provider는 LSEG FXall Cash RFQ다. FXall은 회사에 적용된 다중은행 RFQ와
선도환을 지원하고 FIX 연동 및 거래 이력을 제공한다. 현재 상태는
`onboarding_required`이며 실제 연결 또는 실데이터 확보로 표시하지 않는다.

`tradeflow.integration.fxall_forward_quotes`는 인증된 세션에서 받은 단일
`FXFWD` Quote(S)의 경제 필드만 기존 관측 선도환 스키마로 바꾼다.

- 매수는 Offer spot(190) + Offer forward points(191)
- 매도는 Bid spot(188) + Bid forward points(189)
- 통화쌍(55), 주문통화(15), 수량(38), 결제일(64), 관측시각(60),
  만료시각(62), Quote ID(117)를 필수로 검증
- 계정, LEI, 세션 키, 비밀번호와 원문 FIX 로그는 공용 저장소에 저장하지 않음
- provider/company/tenant는 FIX 본문이 아니라 인증된 connector context에서 주입
- 비용률은 forward points로 추정하지 않고 계약/수수료 자료에서 별도 주입

실제 운영 전에는 LSEG 온보딩, LP 권한, endpoint/credential, 회사 동의,
tenant-private 암호화 저장소를 갖추고 100개 이상의 동일 범위 관측치를
수집해야 한다. 그 전에는 최소분산 헤지비율 모델이 실호가 기반으로
승격되지 않는다.
