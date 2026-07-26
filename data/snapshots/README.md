# 스냅샷 저장소

수집기(`src/tradeflow/integration/`)가 외부 출처에서 받아온 원본을 이 디렉터리에
버전별 파일로 기록합니다. 계산 도구와 지식 규칙은 외부 API가 아니라 **이 파일만**
읽습니다.

파일을 저장소에 커밋하는 이유는 셋입니다.

- 정의서 §9.1 "과거 스냅샷으로 동일 결과를 재현할 수 있다"가 CI에서 그대로 검증됩니다
- 외부 API 장애 시에도 마지막 정상 스냅샷으로 동작합니다 (정의서 §10)
- 테스트가 네트워크 없이 실행됩니다

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
  "retrieved_at": "2026-07-26T09:00:00+00:00",
  "payload": {}
}
```

`source_id`, `version`, `retrieved_at` 세 필드는 `domain.snapshot.SnapshotRef`와
1:1로 대응합니다. 최신성 판정은 `FreshnessPolicy`가 수행하며, SLA를 넘긴 스냅샷은
`STALE`로 처리되어 최종 판단 근거에서 제외됩니다 (정의서 §6.2).

## 주의

- 원본을 가공해서 저장하지 않습니다. 가공은 읽는 쪽의 책임입니다.
- 실제 고객 데이터나 비밀값을 포함하지 않습니다.
- 출처 메타데이터(공식성, 시행일)는 `knowledge/source_registry.json`이 관리합니다.
  이 디렉터리는 원본 보존만 담당합니다.
