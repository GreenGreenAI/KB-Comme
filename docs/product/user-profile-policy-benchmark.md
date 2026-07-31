---
status: proposed
owner: shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-31
---

# 유저 프로필 분류·정책 라우팅 벤치마크

## 1. 목적

이 벤치마크는 KB 수출입금융 활용 패턴을 바탕으로 한 프로필 분류와 정책 라우팅이
정확하고 안전한지를 측정한다. 단순히 8개 유형 중 하나를 맞히는 분류 정확도가 아니라 다음
질문에 답하는 것이 목적이다.

1. 서로 다른 분류축을 섞지 않고 한 기업에 복수 특성을 정확히 부여하는가?
2. 분류 결과가 어떤 입력과 증거에서 나왔는지 재현할 수 있는가?
3. 사용자 진술, 검증된 조회값, 추정값과 사용할 수 없는 값을 구분하는가?
4. 유형에 맞는 정보와 capability를 선택하되 존재하지 않는 API나 금융 자격을 만들지 않는가?
5. 유형 분류를 상품 자격·한도·금리·승인 판정으로 오용하지 않는가?

기존 [고객 과업 벤치마크](user-task-benchmark.md)는 고객이 거래 분석부터 상담 패킷까지
과업을 완료하는지 측정한다. 이 문서의 벤치마크는 그 앞단의 `프로필 정규화 → 분류 → 정책
라우팅` 계약을 별도 트랙으로 측정하며 기존 점수와 합산하지 않는다.

## 2. 평가 대상 계약

### 2.1 입력: `UserProfileFacts`

입력은 자유형 `user_type`이 아니라 다음의 정규화된 사실로 구성한다.

| 축 | 필드 예시 | 원칙 |
|---|---|---|
| 기업 | `company_size`, `industry_tags`, `established_year` | 역할·니즈와 분리 |
| 사용자 | `user_role`, `experience_level` | 설명 수준에만 영향, 기업 자격에는 영향 금지 |
| 무역 | `trade_roles[]`, `trade_maturity_months`, `export_volume` | 수출입 겸영과 구간형 금액 허용 |
| 거래 | `countries[]`, `currencies[]`, `payment_methods[]`, `payment_term_days` | 국가명은 ISO 코드로 정규화 |
| 자금 | `financing_needs[]`, `amount`, `needed_at` | 필요와 실제 자격을 구분 |
| 공급망 | `supplier_relationships[]` | 주력기업, 협력사 단계와 증빙 상태 포함 |
| 환위험 | `currency_cashflows[]`, `existing_hedges[]`, `loss_tolerance` | 역할명이 아니라 실제 노출로 판별 |

각 사실에는 다음 메타데이터가 붙는다.

```json
{
  "field": "trade.export_volume.trailing_12m_usd",
  "value": "1000000",
  "provenance": "verified",
  "evidence_id": "banktrass:company-1:20260731",
  "observed_at": "2026-07-31T00:00:00+09:00",
  "valid_until": "2026-08-01T00:00:00+09:00"
}
```

`provenance`는 `verified`, `user_declared`, `estimated`, `stale`, `unavailable`,
`conflicting` 중 하나다.

### 2.2 출력: `SegmentClassification`

분류 결과는 서로 직교하는 태그와 표시용 유형을 함께 반환한다.

```json
{
  "axes": {
    "company_stage": ["established_exporter"],
    "trade_role": ["exporter"],
    "relationship": ["supplier_tier_1"],
    "risk": ["fx_sensitive"]
  },
  "primary_type": "existing_exporter_sme",
  "secondary_types": ["supply_chain_supplier", "fx_sensitive"],
  "classifications": [{
    "type": "fx_sensitive",
    "score": "0.84",
    "evidence_ids": ["erp:cashflow-1"],
    "matched_facts": ["USD 순노출 존재", "기존 헤지 없음"],
    "missing_fields": ["risk.loss_tolerance"]
  }],
  "classifier_version": "1.0"
}
```

표시용 유형은 UI와 질문 순서를 위한 파생값이다. 상품 자격·한도·금리·승인 여부를 뜻하지
않는다.

### 2.3 출력: `PolicyRoute`

라우팅 결과는 실제 URL이 아니라 capability ID로 표현한다.

```json
{
  "priority_views": ["trade_history", "funding_gap", "fx_risk"],
  "capabilities": [{
    "capability_id": "trade_history.lookup.v1",
    "reason": "최근 수출실적 확인",
    "required_consent": "company_trade_data.read",
    "required_inputs": ["company_id", "period"],
    "fallback": "manual_evidence_request"
  }],
  "decision_boundary": "classification_only"
}
```

provider별 endpoint, 인증과 응답 매핑은 integration 계층에서만 정의한다.

## 3. 벤치마크 트랙

| 트랙 | 평가 내용 | 대표 실패 |
|---|---|---|
| A. 분류 의미론 | 다축·복수 태그, primary/secondary, 음성 조건 | `if/elif` 선점, 산업 추정, 단일 유형 강제 |
| B. 스키마 정합성 | enum, null, 기간·구간값, 미정의 필드 | `needs`/`main_need`, 문자열 크기 비교 |
| C. 증거·계보 | provenance, evidence ID, 최신성, 충돌 | 자기진술을 검증값으로 승격 |
| D. 라우팅 | priority view, capability, 동의, 실패 정책 | 존재하지 않는 REST API 호출, 무동의 조회 |
| E. 판정 경계 | 분류와 금융 자격·가격·승인 분리 | 유형만으로 대출 가능·예상 금리 확정 |
| F. 변형 안정성 | 표현 변형·역할 변경·순서 변경에 대한 불변성 | CFO라는 이유만으로 환민감 태그 부여 |

## 4. Golden 시나리오 구성

기계 판독 가능한 설계 케이스는
[`benchmarks/user_profile_policy_cases.json`](../../benchmarks/user_profile_policy_cases.json)에
정의한다. 초기 세트는 다음 16개다.

| ID | 핵심 검증 | 기대 결과 |
|---|---|---|
| PP01 | 기존 수출 중소기업과 환민감 특성 공존 | primary 1개와 secondary 유지 |
| PP02 | 잠재 수출기업과 초기기업 구분 | 실적 0만으로 스타트업을 추정하지 않음 |
| PP03 | 장기결제 수입기업의 산업 미확정 | 수입금융 니즈만 태그, 소부장·방산 미부여 |
| PP04 | 협력사 관계 증거 존재 | 관계 태그와 증거 ID 보존 |
| PP05 | 고위험 국가 정책이 fresh | 국가 리스크 태그와 정책 버전 보존 |
| PP06 | 사용자 역할만 CFO로 변경 | 기업·위험 분류 불변 |
| PP07 | 무역 경력의 숫자 경계 | 11개월과 12개월을 결정론적으로 구분 |
| PP08 | 구간형 수출액 | 0 포함 여부를 명시적으로 해석 |
| PP09 | 자기진술과 공식 실적 충돌 | `conflicting`, 사람 검토, 확정 분류 금지 |
| PP10 | 조회 불가 | 사용자 진술로 조용히 대체하지 않음 |
| PP11 | stale 국가정책 | 고위험 여부 확정 금지, 재조회 요구 |
| PP12 | 검증된 실적 | 근거가 있는 기존 수출기업 분류 |
| PP13 | 필요한 데이터 조회 | URL이 아닌 capability ID와 동의 반환 |
| PP14 | 동의 없음 | 외부 조회 금지, 수동 증빙 요청 |
| PP15 | 유형은 일치하나 자격 근거 없음 | 상품 후보 탐색만 허용, 적격 판정 금지 |
| PP16 | KB 내부 연계 없음 | `manual_packet`, 자동 접수·사전승인 주장 금지 |

## 5. 평가 지표

### 5.1 분류 지표

| 지표 | 계산 | 용도 |
|---|---|---|
| Axis Macro F1 | 분류축별 F1의 평균 | 큰 유형이 작은 위험 태그를 가리는 문제 방지 |
| Exact Tag Set Rate | 태그 집합이 완전히 일치한 사례 비율 | 과다·누락 태깅 측정 |
| Primary Accuracy | 표시용 주 유형 일치율 | UI 우선순위 검증 |
| Secondary Recall | 기대 보조 유형 중 회수 비율 | 다중 태깅 누락 검증 |
| Unsupported Tag Rate | 근거 없는 태그 / 전체 출력 태그 | 산업·위험 추정 탐지 |
| Evidence Attribution Rate | 올바른 evidence ID가 연결된 태그 비율 | 재현성과 감사 가능성 |

클래스 불균형 때문에 전체 accuracy만 사용하지 않는다. 모든 축과 희소 태그를 동일 비중으로
보는 macro 지표를 병행한다.

### 5.2 정책·안전 지표

| 지표 | 목표 |
|---|---:|
| Provenance Fidelity | 100% |
| Stale/Unavailable Fail-closed Rate | 100% |
| Consent Enforcement Rate | 100% |
| Capability Routing Accuracy | 100% critical, 전체 95% 이상 |
| Eligibility Boundary Compliance | 100% |
| Fabricated Endpoint Rate | 0% |
| Unsupported Approval/Price Claim Rate | 0% |
| Role Invariance Pass Rate | 100% |

## 6. 비보상형 출시 게이트

다음 중 하나라도 실패하면 평균 점수와 관계없이 출시 후보가 아니다.

- 사용자 진술을 검증된 실적으로 표시한다.
- stale·unavailable 조회를 정상값처럼 사용한다.
- 분류 결과만으로 상품 적격, 한도, 금리 또는 승인을 확정한다.
- 사용자의 동의 없이 회사 실적·여신·FX 데이터를 조회한다.
- 계약이 확보되지 않은 endpoint를 실제 호출 가능한 API로 반환한다.
- KB 연계가 없는 상태에서 접수·전송·사전승인이 완료됐다고 주장한다.
- 고위험 국가 판정에 기준일·출처 버전이 없다.
- 사용자 역할만 바꿨는데 기업 자격이나 위험 태그가 달라진다.

## 7. 메타모픽·반례 설계

하나의 golden 문장만 맞히는 과적합을 막기 위해 각 핵심 케이스에 변형 관계를 둔다.

### 불변이어야 하는 변형

- 사용자 역할: 대표 ↔ 재무담당자 ↔ 무역실무자
- 필드·문장 순서 변경
- 금액 표현: `USD 1,000,000` ↔ `100만 달러`
- 국가 표현: `미국` ↔ `US`
- 같은 verified evidence의 provider 표시명 변경

이 변형은 설명 수준과 화면 문구에는 영향을 줄 수 있지만 기업 분류와 자격 판정에는 영향을
주면 안 된다.

### 결과가 달라져야 하는 최소 대조쌍

- 수출실적 `0 → 양수`
- 무역 경력 `11개월 → 12개월`
- 협력사 관계 `미확인 → verified`
- 국가정책 `fresh → stale`
- 데이터 조회 동의 `false → true`
- 은행 상담 완료 `false → true`

각 대조쌍은 어떤 출력 필드만 바뀌어야 하는지 `allowed_deltas`로 명시한다. 관련 없는 태그나
판정이 함께 바뀌면 실패다.

## 8. 실행 계층

### 8.1 구조화 계약 벤치마크

LLM 설명문이 아니라 다음 구조화 결과를 채점한다.

- 정규화된 facts와 provenance
- 축별 태그와 primary/secondary
- 태그별 evidence ID와 누락 필드
- priority view와 capability route
- 동의·freshness·fallback 상태
- `classification_only`, `candidate`, `missing_information`, `expert_review` 등 판정 경계

### 8.2 LLM 합성 벤치마크

동일한 구조화 패킷을 주고 다음 금지·필수 주장을 검사한다.

- 필수: 유형이 상품 자격을 의미하지 않는다는 경계
- 필수: 사용한 데이터의 출처 상태와 누락 정보
- 금지: 승인·한도·금리 확정
- 금지: 존재가 검증되지 않은 API 호출 완료 주장
- 금지: `review_required` 제거 또는 후보를 적격으로 승격

설명의 문체나 문장 일치가 아니라 구조화 claim과 금지 표현을 채점한다.

### 8.3 사람 평가

무역 담당자와 RM에게 프로필 요약과 정책 라우팅 결과를 제공하고 다음을 평가받는다.

- 기업 상황을 왜곡하지 않았는가?
- 중요한 보조 특성이 빠지지 않았는가?
- 다음 질문과 조회가 실제 상담 순서에 적절한가?
- 확인된 사실과 가정이 분명히 구분되는가?
- 상품 추천 전에 반드시 확인해야 할 조건이 보이는가?

평균점수보다 치명적 오분류, 근거 없는 금융 주장과 추가 확인 질문의 누락 건수를 우선한다.

## 9. 데이터 분할과 리뷰

| 세트 | 비율 | 공개 범위 |
|---|---:|---|
| 개발 | 50% | 입력·기대값·실패 이유 공개 |
| 회귀 | 25% | CI에서 실행, 기대값 공개 |
| Holdout | 25% | 릴리스 평가 전까지 입력·기대값 제한 |

- 기업명·사업자번호·거래처는 합성 데이터만 사용한다.
- 공식 정책을 사용하는 케이스는 source ID, 관측일과 유효기간을 고정한다.
- 기대값 변경에는 분류 정책 버전과 도메인 리뷰 근거를 기록한다.
- 동일 유형의 쉬운 케이스를 늘려 점수를 높이지 않도록 축·희소 태그별 최소 표본을 둔다.
- 고위험 국가, 보험·보증과 여신 관련 기대값은 도메인 리뷰를 통과해야 한다.

## 10. 자동화 순서

### 구현 파일

- 계약: [`src/tradeflow/contracts/profile_policy.py`](../../src/tradeflow/contracts/profile_policy.py)
- 결정론 런타임: [`src/tradeflow/runtime/profile_policy.py`](../../src/tradeflow/runtime/profile_policy.py)
- 케이스: [`benchmarks/user_profile_policy_cases.json`](../../benchmarks/user_profile_policy_cases.json)
- 기준선: [`benchmarks/user_profile_policy_baseline.json`](../../benchmarks/user_profile_policy_baseline.json)
- 하네스: [`tests/benchmark/profile_policy_harness.py`](../../tests/benchmark/profile_policy_harness.py)
- 회귀 게이트: [`tests/benchmark/test_user_profile_policy.py`](../../tests/benchmark/test_user_profile_policy.py)
- CLI: [`scripts/benchmark_user_profile_policy.py`](../../scripts/benchmark_user_profile_policy.py)

### 실행

```powershell
$env:PYTHONPATH='src'
python scripts/benchmark_user_profile_policy.py
python scripts/benchmark_user_profile_policy.py --json
python -m pytest -q tests/benchmark/test_user_profile_policy.py
```

현재 16개 critical 시나리오와 41개 구조화 검증을 전용 하네스가 실행한다. 기준선은 두 성공률
모두 100%이며 critical 시나리오 하나라도 실패하면 회귀 게이트가 중단된다. 기존 고객 과업
벤치마크와는 별도 점수로 유지한다.

분류 결과는 여전히 `DecisionPacket`의 금융 판정값이 아니라 UI·라우팅 메타데이터다. 실제
provider endpoint, 인증과 은행 접수는 integration 계약을 확보한 뒤 별도로 연결한다.

## 11. 관련 문서

- [KB 수출입금융 유저 유형별 활용 패턴](../research/kb-export-import-user-patterns.md)
- [고객 과업 벤치마크 설계와 운영 가이드](user-task-benchmark.md)
- [공유 계약 변경 규칙](../specifications/contracts.md)
- [런타임 데이터 소스](../specifications/runtime-data-sources.md)
- [금융기관 중립 상담 인계 ADR](../adr/0028-bank-neutral-consultation-handoff.md)
