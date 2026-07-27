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
- 공개 기준데이터: 커밋된 `data/snapshots/`와 무결성 검증 리더
- 고객 거래 입력: Git 제외 `data/runtime/` 또는 암호화된 운영 저장소
- 정규화 데이터: `TradeFeedData`, `FxSeries`와 `TradeProgram`
- 설명과 검토 기록: 근거 패킷을 통해 계산 결과와 연결

```text
공식/ERP API
  → integration 수집기
  → 원문 SnapshotRef(source/version/time/hash)
  → domain 스키마·무결성·최신성 검증
  → TradeProgram / FxSeries
  → FactCatalog + evidence-bound FactAssembler
  → case별 trade_support_case / fx_compliance
  → 결정론 계산·규칙
  → EvidenceDescriptor
  → DecisionPacket
  → LLM 설명
```

스냅샷이 없거나, 손상되었거나, 스키마가 다르거나, SLA를 넘기면 계산에 진입하지
않는다. LLM은 이 실패를 보정하거나 누락 데이터를 추정하지 않는다.

Supplemental fact는 evidence role만 같아서는 부족하다. 근거가 해당 case ID를
identifier로 포함하고 `payload.facts`에 같은 field/value를 명시해야 규칙 입력으로
승격된다. 케이스 판정은 `(subject_id, rule_id)`로 식별한다.

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

## 결정론 계층과 LLM 경계

계산, 규칙 판정, 출처 상태, 근거 충족과 검토 필요 여부는 LLM을 사용하지 않는다.
이 결과는 [ADR-0007](../adr/0007-llm-execution-boundary-and-decision-packet.md)의
`DecisionPacket`으로 봉인한 뒤 합성 계층에 전달한다.

LLM은 패킷을 설명하는 표현 계층이다. 판단 상태와 수치를 바꾸거나 패킷 밖의 근거를
추가할 수 없으며, 구조화된 `SynthesisResult`가 결정론 검증을 통과한 경우에만
사용자 응답으로 승격할 수 있다.
