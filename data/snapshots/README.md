# 스냅샷 저장소

수집기(`src/tradeflow/integration/`)가 **공개 기준데이터** 출처에서 받아온 원본을
이 디렉터리에 버전별 파일로 기록합니다. 계산 도구와 지식 규칙은 외부 API가 아니라
**이 파일만** 읽습니다.

공개 기준데이터 파일을 저장소에 커밋하는 이유는 셋입니다.

- 정의서 §9.1 "과거 스냅샷으로 동일 결과를 재현할 수 있다"가 CI에서 그대로 검증됩니다
- 외부 API 장애 시에도 마지막 정상 스냅샷으로 동작합니다 (정의서 §10)
- 테스트가 네트워크 없이 실행됩니다

고객 거래·ERP 원장·잔액은 이 디렉터리에 저장하거나 Git에 커밋하지 않습니다.
그 데이터는 `.gitignore`로 차단된 `data/runtime/` 또는 운영 환경의 암호화된 비공개
저장소에 보관합니다. 공개 스냅샷과 고객 스냅샷은 봉투 형식은 같지만 저장 위치,
접근권한, 보존·삭제 정책이 다릅니다.

## 경로 규칙

```text
data/snapshots/<source_id>/<version>.json
```

`version`은 정렬 가능한 값을 사용합니다. 영업일 단위 출처는 `YYYY-MM-DD`를 씁니다.

## 봉투 형식

원본 응답은 `payload`에 그대로 보존하고, 재현에 필요한 식별 정보를 바깥에 둡니다.

```json
{
  "source_id": "ECOS_USD_KRW",
  "version": "2026-07-26",
  "observed_at": "2026-07-26T00:00:00+09:00",
  "retrieved_at": "2026-07-26T09:12:31+09:00",
  "content_hash": "sha256:...",
  "payload": {}
}
```

다섯 필드는 `domain.snapshot.SnapshotRef`와 1:1로 대응합니다.

- **`observed_at`**: 데이터가 서술하는 시점. 출처가 고시한 기준시각을 씁니다.
- **`retrieved_at`**: 우리가 받아온 시점.
- **`content_hash`**: `payload`의 해시. 과거 결과가 참조한 스냅샷이 이 파일임을
  증명하는 데 쓰입니다.

두 시각은 출처가 늦게 고시하거나 캐시된 응답을 줄 때 어긋납니다. **오래된 데이터를
오늘 받아왔다고 해서 최신이 되지 않으므로**, 최신성 판정은 `observed_at`을 먼저
봅니다. `FreshnessPolicy`는 두 나이를 모두 검사하며, SLA를 넘긴 스냅샷은 `STALE`로
처리되어 최종 판단 근거에서 제외됩니다 (정의서 §6.2).

### 시간대

**두 시각 모두 오프셋을 반드시 포함합니다.** 시간대 없는 값은 읽는 쪽이 UTC로
간주하지 않고 거부합니다. 수집 시각을 임의로 해석하면 그 위에 쌓인 모든 최신성
판정이 조용히 어긋나기 때문입니다. 수집기는 출처의 고시 시간대를 그대로 기록합니다
(ECOS는 KST).

## 수집된 출처

### `ECOS_USD_KRW`

한국은행 ECOS의 원/미국달러 매매기준율입니다. 코드는 추측하지 않고 ECOS의
`StatisticTableList`·`StatisticItemList`로 조회해 확정했습니다.

| 항목 | 값 |
|---|---|
| 통계표코드 | `731Y001` (3.1.1.1. 주요국 통화의 대원화환율) |
| 항목코드 | `0000001` (원/미국달러(매매기준율)) |
| 주기 | `D` (영업일) |
| 단위 | 원 |
| 제공 기간 | 1964-05-04 ~ |

수집 명령은 다음과 같습니다. 인증키는 `ECOS_API_KEY` 환경변수 또는 상위
디렉터리의 `.env`에서 읽으며, 저장소에 커밋하지 않습니다.

```bash
PYTHONPATH=src python -m tradeflow.integration.ecos 20160101 20260724
```

`observed_at`은 응답에 담긴 **가장 최근 영업일의 00:00 KST**입니다. ECOS는 일별
데이터에 시각을 주지 않으므로, 하루의 시작으로 두어 데이터가 실제보다 조금 더
늙어 보이게 합니다. 최신성 판정이 틀린다면 안전한 방향으로 틀리게 하려는 것입니다.

전체 기간을 반복 수집하면 겹치는 스냅샷이 쌓입니다(10년치 1건이 약 1.2MB).
최초 1회만 장기간을 받고, 이후에는 최근 구간만 수집하십시오.

### `KOREAEXIM_REFERENCE_FX`

한국수출입은행 환율 정보 Open API의 AP01 다통화 기준환율입니다. 신규 공식 도메인
`oapi.koreaexim.go.kr`만 사용하고 인증키는 snapshot에 저장하지 않습니다. 응답은
요청 `search_date`와 함께 schema 1.0 wrapper에 보존하며, `result`가 성공인 전체 행을
`ReferenceFxCatalog`로 검증합니다.

이 값은 기준·분석용이며 은행이 기업에 제시한 실행 가능 호가가 아닙니다. `JPY(100)`
같은 고시단위를 임의로 버리지 않고 raw 단위와 배수를 함께 보존합니다.

### `KNOWLEDGE_SOURCES`

지식 규칙이 인용하는 **공식 출처가 아직 그 내용 그대로인지** 확인한 기록입니다.
다른 스냅샷과 달리 데이터를 담지 않고 검증 결과만 담습니다.

이 스냅샷이 필요한 이유는 규칙 엔진의 판정 순서 때문입니다. `KnowledgeRepository`는
조건을 보기 **전에** 출처 상태를 보고, `ACTIVE`가 아닌 출처를 인용한 규칙은
사용자가 무엇을 답하든 자동 판정에서 제외합니다. 검증 기록이 런타임에 닿지 않으면
전 규칙이 `EXPERT_CONFIRMATION_REQUIRED`로 떨어져 답이 비어버립니다.

`knowledge/source_monitors.json`의 `required_markers`는 시행일·조문 번호처럼 그
버전을 특정하는 문자열입니다. 페이지에서 마커가 사라졌다면 우리가 읽고 규칙을 만든
그 텍스트가 아니게 된 것이므로 해당 출처를 `STALE`로 기록합니다.

| 결과 상태 | 런타임 해석 | 뜻 |
|---|---|---|
| `verified` | `FRESH` | 마커가 모두 있음 |
| `changed_or_unavailable` | `STALE` | 받아봤더니 마커가 없음 |
| `unreachable` | *(매핑에서 제외)* → `FRESHNESS_UNKNOWN` | 받아보지 못함 |

`unreachable`을 `STALE`로 적지 않는 것은 의도된 구분입니다. 둘 다 자동 판정을
멈추지만, 전자는 출처에 대해 우리가 아무것도 관측하지 못했다는 뜻이고 후자는
바뀌었다는 관측입니다. 서버 인증서 문제를 법령 개정처럼 보고할 수는 없습니다.

```bash
PYTHONPATH=src python scripts/check_sources.py --write
```

`--write`는 전체 매니페스트를 요구합니다. 일부만 조회한 결과를 기록하면 조회하지
않은 출처가 판정 없는 상태로 남아 사실상 `FRESHNESS_UNKNOWN`이 되는데, 이는 검증
실패와 구분되지 않기 때문입니다. 한 출처가 실패해도 나머지는 기록됩니다 —
`www.koreaexim.go.kr`은 현재 중간 인증서를 누락해 `unreachable`로 남습니다.

원문은 저장하지 않습니다. 매니페스트의 `storage_policy`가 출처별 재배포 조건을
확인하기 전까지 응답 본문 보존을 금지하므로, HTTP 지문과 마커 판정만 남깁니다.

`observed_at`은 조회 시각입니다. 검증은 그 순간의 페이지 상태에 대한 관측이므로
관측 시각과 수집 시각이 같습니다. 30일이 지난 검증 기록은 읽는 쪽에서 거부합니다.

## 소비 규칙

### `BIZINFO_SUPPORT_API`

기업마당 지원사업 목록은 `BIZINFO_API_KEY` 인증키로 수집하고 원문 JSON을 공통
스냅샷 봉투에 저장합니다. 인증키는 파일이나 레지스트리에 기록하지 않습니다.

스냅샷은 `BizinfoSupportV1Parser`를 통해 `SupportProgramCatalog`로 읽습니다. 이
객체는 지원사업 탐색 후보이며, 목록 데이터만으로 기업의 자격이나 추천 여부를
확정하지 않습니다. 상세 공고의 조건이 근거 규칙으로 검토되기 전에는 최종 판단에
사용할 수 없습니다.

- `latest_snapshot_path`는 파일명 정렬이 아니라 `observed_at` 기준으로 최신본을 고른다.
- `read_snapshot`은 해시와 경로의 source/version 일치를 검증한다.
- 거래피드는 `read_trade_feed_snapshot`, ECOS는 `read_ecos_usd_krw_snapshot`으로
  스키마를 검증한 뒤 사용한다.
- 소비자는 작업별 `FreshnessPolicy`를 반드시 전달하며, SLA를 넘긴 데이터는
  `StaleDatasetError`로 중단한다.
- 거래 스냅샷의 source/version/hash는 `TradeProgram.input_snapshots`를 거쳐
  `DecisionPacket` 근거까지 전달한다.

## 주의

- 원본을 가공해서 저장하지 않습니다. 가공은 읽는 쪽의 책임입니다.
- 실제 고객 데이터나 비밀값을 포함하지 않습니다.
- 출처 메타데이터(공식성, 시행일)는 `knowledge/source_registry.json`이 관리합니다.
  이 디렉터리는 원본 보존만 담당합니다.
