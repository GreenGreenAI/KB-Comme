# ADR-0003: 스냅샷 계약의 위치와 integration 리프

- 상태: 제안 (역할 A 승인 대기)
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

## 결정

### 1. 스냅샷 값객체와 최신성 판정은 `domain/`에 둔다

`domain/snapshot.py`에 `SnapshotRef`(source_id, version, retrieved_at)와
`FreshnessPolicy`를 둔다. I/O 없이 값과 순수 판정만 담으므로 `domain`이 아무것도
import하지 않는다는 ADR-0001 제약을 지키며, `tools`와 `knowledge` 양쪽이 쓸 수 있다.

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

## 결과

- `domain/snapshot.py`, `domain/enums.Freshness` 신설 — `domain/` 변경이므로 역할 A 승인 필요
- `src/tradeflow/integration/` 신설 (역할 B 소유), `data/snapshots/` 신설
- 경계 테스트에 `integration` 규칙 2종 추가
- 미결: `SourceRecord.status_on`(출처 시행일)과 `FreshnessPolicy`(수집 최신성)는 서로
  다른 축이다. 둘을 어떻게 합성해 최종 `STALE`을 결정할지는 역할 A의 §6.3 근거 레코드
  보강 시점에 정한다.
