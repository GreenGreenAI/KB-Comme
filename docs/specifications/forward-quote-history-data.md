---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-28
---

# 관측 선물환 이력 데이터 계획

관련 이슈: #29

## 목적

헤지 challenger의 경제적 성과와 최소분산 비율을 평가하려면 의사결정 시점에 실제로
관측됐고 해당 기업이 사용할 수 있었던 선물환 호가가 필요하다. 현물환율, 이론
forward curve, 거래소 선물 또는 사후 체결가를 당시 은행 호가로 표시해서는 안 된다.

구조 계약은
[`observed_forward_quote_history.schema.json`](../../knowledge/schemas/observed_forward_quote_history.schema.json)을
사용한다.

## 후보 데이터

| 후보 | 용도 | 운영 승격 데이터 여부 |
|---|---|---|
| 기업의 은행 RFQ·Treasury Management System export | 기업·시각·만기·명목금액별 실제 가용 호가와 비용 | 가능, 최우선 |
| 은행 또는 FX provider의 계약형 quote API | point-in-time bid/offer와 유효시간 | 가능, 계약·권한 검토 필요 |
| [K-SURE 보장환율 공개 데이터](https://www.data.go.kr/data/15064336/fileData.do) | 보장환율·기간별 swap point·시장평균환율 benchmark | 불가, 보험 기준가격이지 기업별 은행 호가가 아님 |
| [KRX 미국달러선물 상품](https://global.krx.co.kr/contents/GLB/02/0201/0201040601/GLB0201040601.jsp) | 상장 선물의 시장 hedge benchmark | 불가, 표준화 선물이며 OTC forward가 아님 |
| [CME KRW futures](https://www.cmegroup.com/markets/fx/fx-delivery.html) | 해외 시장 stress·유동성 benchmark | 불가, cash-settled 표준상품 |
| 한국수출입은행 기준환율·ECOS 현물 | spot origin과 실현 환율 | 불가, forward quote가 아님 |
| 금리평가식으로 생성한 synthetic forward | 민감도 분석 | 불가, `synthetic`으로만 표시 |

2026년 6월 공개된 K-SURE 보장환율 자료는 약 11만 건의 산정일자, 통화,
기간별 swap point와 보장환율을 제공하므로 challenger의 시장 방향성 benchmark로
유용하다. 그러나 기업의 신용, 거래은행, 명목금액과 quote 유효시간을 포함하지 않아
`quote_basis=observed_forward_quote` 승격 조건을 충족하지 않는다.

## 보안·보존

- 저장 범위는 `tenant_private_financial`이며 공개 snapshot에 넣지 않는다.
- tenant와 company scope를 요청 주체의 권한에서 검증한다.
- 원문 evidence는 암호화하고 quote record에는 canonical hash를 남긴다.
- 계좌번호, 담당자 이름, 연락처와 인증정보는 모델 데이터에서 제거한다.
- provider 계약의 재배포·파생 통계 허용 범위를 확인한다.
- 삭제·보존기간은 고객 계약과 금융기록 정책을 따르며 학습 데이터로 재사용하지 않는다.
- 테스트 fixture에는 실제 기업·provider 식별자와 실호가를 넣지 않는다.

## 정합성·무누수 조건

- `observed_at <= validation origin < valid_until`
- origin 시점에 알려진 spot snapshot만 연결
- 결제일·통화쌍·side·명목금액 범위가 분석 case와 일치
- provider와 company applicability가 검증된 record만 운영 평가에 사용
- champion과 challenger는 동일한 origin과 quote를 사용
- 사후 체결·결제 결과는 점수 계산에만 사용하고 모델 입력에 포함하지 않음

## 수집 순서

1. 내부 또는 협력기업의 익명화된 RFQ/TMS export 확보 가능성을 확인한다.
2. provider 계약, 이용목적, 보존기간과 재현 가능한 quote ID를 합의한다.
3. `JsonForwardQuoteHistoryAdapter`로 HTTPS 정규화 feed를 수집하고
   tenant scope를 대조한 뒤, 호출자가 지정한 비공개·암호화 저장소에 immutable raw
   snapshot을 기록한다. 저장소의 공개 `data/snapshots/`는 이 데이터의 기본 경로가
   아니다.
4. 최소 100개 동일 만기 origin을 확보하고 품질 보고서를 만든다.
5. 공개 benchmark를 별도 adapter로 수집해 실제 quote 성과와 비교한다.
6. 세 역할 승인 전에는 model promotion을 실행하지 않는다.

## 구현된 수집 경계

- `parse_observed_forward_quote_payload`는 스키마 버전, decimal 문자열, 통화·명목금액,
  호가 유효시간, provider 검증, company applicability, spot snapshot과 evidence hash를
  결정론적으로 검증한다.
- `JsonForwardQuoteHistoryAdapter`는 HTTPS와 응답 크기 제한을 강제하고 bearer
  credential을 snapshot이나 오류에 남기지 않는다.
- adapter의 tenant와 payload tenant가 다르면 저장 전에 거부한다.
- `read_observed_forward_quote_snapshot`은 immutable snapshot identity와 tenant scope를
  다시 검증한다.
- 실제 endpoint, credential, 암호화 저장소와 데이터 계약은 고객·provider 계약 후
  운영 환경에서 주입한다. 이 저장소에는 실제 기업 호가 fixture를 넣지 않는다.
