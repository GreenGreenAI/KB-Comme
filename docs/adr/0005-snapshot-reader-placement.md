---
status: accepted
owner: platform-runtime
reviewers: knowledge-domain, platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0005: 스냅샷을 읽는 계층

- 상태: 승인
- 날짜: 2026-07-26
- 관련: ADR-0001, ADR-0003, MVP 아키텍처 정의서 §6.2, §9.1

## 배경

ADR-0003은 계층 간 공유를 실행 코드가 아니라 **커밋된 파일**로 하기로 정하고 다음
그림을 남겼다.

```text
data/snapshots/*.json ──→ tools/ 가 읽음
                     └──→ knowledge/ 가 읽음
```

그러나 **누가 그 파일을 여는지**는 정하지 않았다. 실제로 파일을 여는 `read_snapshot`은
`integration/snapshot_store.py`에 있고, 경계 규칙상 `tools`·`knowledge`·`runtime`은
모두 `integration`을 참조할 수 없다. 그림이 말한 "읽음"을 수행할 주체가 없다.

§5.2 변동성 생성기를 구현하며 드러났다. 도구를 순수 함수로 만들어 시계열을 인자로
받게 하여 도구 자체는 문제가 없으나, Agent Layer(§4.1)가 스냅샷을 열어 워커에 넘겨야
하는 시점에 `runtime`이 같은 벽에 막힌다.

이 ADR은 ADR-0003을 대체하지 않는다. 값객체를 `domain`에 두고 수집을 리프로 격리하며
파일로 공유한다는 결정은 그대로 유효하다. 그 결정이 남긴 빈칸 하나를 채운다.

## 고려한 선택지

| 선택지 | 장점 | 비용 |
|---|---|---|
| `tools`의 `integration` 참조 허용 | 코드 이동 없음 | ADR-0003이 이미 거부한 방향. 네트워크 I/O가 계산 계층에 딸려 들어옴 |
| `runtime`만 `integration` 참조 허용 | 변경 최소 | 리프 속성이 깨져 에이전트가 요청 도중 수집을 호출할 수 있게 됨 |
| 각 계층이 읽기를 자체 구현 | 경계 무변경 | 봉투 파싱과 해시 대조가 3벌로 갈라짐. 한쪽만 고쳐지면 무결성 검사가 조용히 달라짐 |
| `contracts`에 Protocol을 두고 주입 | 정석적 역전 | `tools`는 `contracts`도 못 봄. 조립 지점을 새로 만들어야 함 |
| **읽기를 `domain`으로** (채택) | 모든 소비자가 도달 가능. 리프 속성 유지 | 스냅샷 모듈이 두 계층에 나뉨 |

## 결정

### 1. 읽기는 `domain/snapshot_file.py`, 생성은 `integration/`

```text
domain/snapshot.py       SnapshotRef · FreshnessPolicy          (변경 없음)
domain/snapshot_file.py  canonical_json · content_hash
                         snapshot_path · read_snapshot          (신설)
        ▲                        ▲              ▲
        │                        │              │
integration/            tools/         knowledge/ · runtime/
snapshot_store.py       (읽기)          (읽기)
build_envelope
write_snapshot          (생성 — 여기만 남는다)
```

분할 기준은 **"스냅샷이 무엇인가"와 "스냅샷이 어떻게 만들어지는가"** 다. 식별·탐색·
읽기·검증은 스냅샷의 정의에 속하므로 `domain`에 두고, 봉투 조립·충돌 감지·영속화는
출처를 아는 `integration`에 남긴다.

`integration`은 `domain`을 참조할 수 있으므로(ADR-0003) 의존 방향은 그대로다. 어떤
모듈도 `integration`을 import하지 않는다는 리프 속성도 유지된다.

### 2. `domain`이 파일을 여는 것은 ADR-0003과 모순되지 않는다

`read_snapshot`은 커밋된 로컬 파일을 여는 결정론적 연산이며 네트워크에 닿지 않는다.
ADR-0003이 택한 "런타임 의존이 아니라 데이터 의존"이 바로 이것이다. 네트워크 I/O는
`integration`에 그대로 남는다.

### 3. 기존 파일은 최소한으로 건드린다

이미 승인된 `domain/snapshot.py`는 수정하지 않고 새 모듈을 신설한다. 값객체와 파일
접근이 한 파일에 섞이지 않으며, 역할 A가 검토할 변경 범위가 좁아진다.

## 결과

- `domain/snapshot_file.py` 신설 — `domain/` 변경이므로 역할 A 승인 필요
- `integration/snapshot_store.py`에서 읽기 관련 요소 제거. 생성 전용으로 축소
- Agent Layer(§4.1)가 스냅샷을 열 수 있게 되어 task 진행이 막히지 않는다
- 경계 규칙 자체는 한 줄도 바꾸지 않는다. `tools`의 `contracts`·`integration` 금지도
  그대로다

## 검증

- `tests/architecture/test_module_boundaries.py`가 변경 없이 통과한다. 경계를 완화하지
  않고 문제를 해결했다는 증거다.
- `domain/snapshot_file.py`는 `domain.snapshot` 외에 어떤 TradeFlow 계층도 참조하지
  않으므로, `domain`이 아무것도 import하지 않는다는 ADR-0001 제약이 유지된다.
- `tests/platform/test_snapshot_store.py`의 읽기·해시 검사가 이동 후에도 그대로
  통과한다. 동작이 아니라 위치만 바뀌었다.
- 미결: 이 테스트는 `tests/platform/`에 있으나 대상 모듈은 `domain/`이다. ADR-0003의
  `test_snapshot.py`와 같은 상황이며, 도메인 테스트의 소유 경계는 역할 A가 정한다.
