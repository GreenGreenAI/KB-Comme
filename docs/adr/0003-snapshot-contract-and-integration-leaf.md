---
status: accepted
owner: platform-runtime
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0003: 스냅샷 계약의 위치와 integration 리프

- 상태: 승인
- 날짜: 2026-07-26
- 관련: ADR-0001, MVP 아키텍처 정의서 §6.1, §6.2, §9.1, §10

## 배경

정의서 §6.2는 "모든 계산은 특정 스냅샷 버전을 참조"하고 SLA 위반 데이터를 `STALE`로
처리하라고 요구한다. 이 요구는 양쪽 계층에 동시에 걸린다.

- 역할 B: ECOS 환율 스냅샷 (§5.2 시장 시나리오 워커의 중단 조건)
- 역할 A: 기업마당·K-SURE 출처의 최신성 판정 (§5.4)

그런데 ADR-0001의 의존 방향은 이를 공유할 자리를 주지 않는다. 특히
`tests/architecture/test_module_boundaries.py`는 `tools`가 `contracts`조차 import하지
못하게 막고 있다. **`tools`가 참조 가능한 계층은 `domain` 하나뿐이다.**

## 고려한 선택지

| 선택지 | 장점 | 비용 |
|---|---|---|
| ADR-0001의 `tools → contracts` 금지를 완화 | 스냅샷을 `contracts`에 둘 수 있음 | 계층 경계를 첫 마찰에서 무르게 함. 다음 공유 타입마다 반복됨 |
| 스냅샷 전용 최하위 계층 신설 | 책임이 명확 | 5계층이 6계층이 됨. 두 사람이 외울 규칙이 늘어남 |
| **값객체는 `domain`, 수집은 리프 + 파일 공유** (채택) | 의존 그래프 무변경. 재현성과 오프라인 테스트가 부수적으로 따라옴 | 수집과 소비가 파일로 느슨하게 연결되어 포맷 계약을 문서로 지켜야 함 |

## 결정

### 1. 스냅샷 값객체와 최신성 판정은 `domain/`에 둔다

`domain/snapshot.py`에 `SnapshotRef`와 `FreshnessPolicy`를 둔다. I/O 없이 값과 순수
판정만 담으므로 `domain`이 아무것도 import하지 않는다는 ADR-0001 제약을 지키며,
`tools`와 `knowledge` 양쪽이 쓸 수 있다.

`SnapshotRef`는 `source_id`, `version`, `observed_at`, `retrieved_at`, `content_hash`를
가진다.

**`observed_at`과 `retrieved_at`을 분리하는 이유**는 둘이 어긋나기 때문이다. 출처가
늦게 고시하거나 캐시된 응답을 주면, 오래된 데이터를 방금 받아오게 된다. `retrieved_at`만
검사하면 이 경우가 `FRESH`로 판정되어 낡은 환율 위에서 변동성이 산출된다.
`FreshnessPolicy`는 `observed_at`을 먼저 보고, 필요하면 수집 나이도 함께 검사한다.

`content_hash`는 필수다. 없으면 과거 결과가 참조한 스냅샷이 지금 이 파일이라는 것을
보일 수 없어 §9.1 재현성이 주장에 그친다.

**시간대 없는 값은 거부한다.** UTC로 간주하는 것은 추정이며, 수집 시각에 대한 추정은
그 위에 쌓인 모든 최신성 판정을 조용히 이동시킨다. 수집기가 오프셋을 명시한다.

이로부터 계층 공통 규칙을 명문화한다.

> **`contracts/` = 행위 계약(Protocol)과 Runtime 전용 값객체.
> `domain/` = 계층 공통 값객체. `tools`가 만져야 하는 타입은 반드시 `domain/`에 둔다.**

`DefaultExposureService`가 `ExposureService`를 import 없이 구조적 타이핑으로 만족시키는
기존 방식이 이 규칙의 근거다. Protocol은 구조로 만족시킬 수 있지만 데이터 타입은
그럴 수 없다.

### 2. 수집은 `integration/` 리프 모듈로 격리하고, 공유는 파일로 한다

새 계층을 의존 그래프에 넣지 않는다. 수집기는 실행되어 **파일을 남기고**, 계산과
지식 계층은 그 파일만 읽는다.

```text
integration/  (리프 — 어떤 모듈도 import 하지 않는다)
    └─ 실행 ─→ data/snapshots/<source_id>/<version>.json  (커밋 대상)
                        │                    │
                 tools/ 가 읽음        knowledge/ 가 읽음
```

`KnowledgeRepository.from_json`이 이미 쓰고 있는 패턴이며, 런타임 의존이 아니라
데이터 의존이므로 의존 방향이 훼손되지 않는다. 부수 효과로 §9.1의 재현성이 CI에서
그대로 검증되고, §10의 "외부 API 장애" 대응이 기본 동작이 되며, 테스트가 네트워크
없이 실행된다.

경계 테스트에 두 방향을 모두 추가한다. `integration`은 `knowledge`·`tools`·`runtime`을
참조하지 못하고, 어떤 모듈도 `integration`을 import하지 못한다.

### 3. MVP에서 기업마당 수집은 자동화하지 않는다

정의서 §6.1은 무역보험·외국환거래 규정을 이미 "수동 하드코딩"으로 규정했다.
기업마당도 같은 방식으로 수동 스냅샷에서 시작한다. 대회 일정에서 역할 A의 시간은
규정 조사에 쓰는 편이 낫고, 수집 자동화는 여유가 생긴 뒤로 미룬다.

ECOS만 자동 수집한다. 백테스트 커버리지(§5.2)에 과거 시계열이 필요하고 그 확보
기간이 역할 B의 리드타임을 지배하기 때문이다.

### 4. 데이터 분류에 따라 저장 위치를 분리한다

위 결정의 “커밋된 파일”은 ECOS처럼 재배포 가능한 공개 기준데이터에만 적용한다.
고객 거래·ERP 원장·잔액은 같은 스냅샷 봉투와 무결성 계약을 사용하되 Git에 커밋하지
않고, 로컬에서는 제외된 `data/runtime/`, 운영에서는 암호화된 비공개 저장소에 둔다.

두 저장소 모두 소비 시 source/version/time/hash, 경로 identity, 스키마와 최신성을
검증한다. 고객 스냅샷의 원문을 결과에 복제하지 않고 `SnapshotRef`만
`TradeProgram`과 `DecisionPacket` 근거로 전달한다. 이 구분은 파일 기반 데이터 의존
결정을 유지하면서 보안 원칙의 “고객 데이터 비커밋”을 만족한다.

## 결과

- `domain/snapshot.py`, `domain/enums.Freshness` 신설 — `domain/` 변경이므로 역할 A 승인 필요
- `src/tradeflow/integration/` 신설 (역할 B 소유), `data/snapshots/` 신설
- 경계 테스트에 `integration` 규칙 2종 추가
- 미결: `SourceRecord.status_on`(출처 시행일)과 `FreshnessPolicy`(수집 최신성)는 서로
  다른 축이다. 둘을 어떻게 합성해 최종 `STALE`을 결정할지는 역할 A의 §6.3 근거 레코드
  보강 시점에 정한다.

## 검증

- `tests/architecture/test_module_boundaries.py`가 양방향을 검사한다. `integration`이
  `knowledge`·`tools`·`runtime`을 참조하지 못하고, 어떤 모듈도 `integration`을 import하지
  못한다. 규칙이 공허하지 않음은 `runtime`에 위반 import를 임시로 넣어 두 규칙이 모두
  실패하는 것으로 확인했다.
- `tests/platform/test_snapshot.py`가 SLA 경계, 버전·해시 누락 거부, 시간대 없는 값의
  거부, KST 등 UTC 아닌 오프셋 처리, 미래 시각의 `STALE` 처리를 검사한다.
- 같은 파일의 `test_old_data_fetched_today_is_stale`이 핵심 회귀다. 7월 1일 데이터를
  7월 27일에 수집한 스냅샷이 `STALE`로 판정되어야 한다.
- 테스트 전체가 네트워크 없이 실행된다. 이것이 파일 기반 공유가 성립한다는 증거다.
