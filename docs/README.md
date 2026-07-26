# TradeFlow 문서 포털

이 디렉터리는 제품 의도, 기술 결정, 구현 계약과 운영 방법을 관리한다. 실행 가능한
규칙과 공식 출처 데이터의 단일 진실 공급원은 `knowledge/`이며, `docs/`는 그 배경과
사용 방법을 설명한다.

## 처음 읽는 순서

1. [제품 비전과 범위](product/vision-and-scope.md)
2. [시스템 아키텍처 개요](architecture/overview.md)
3. [협업 흐름](collaboration/workflow.md)
4. [모듈 소유권](collaboration/ownership.md)
5. [ADR 목록](adr/README.md)

## 문서 지도

| 영역 | 목적 | 기본 소유자 | 진입점 |
|---|---|---|---|
| Product | 문제, 사용자, 범위와 단계 | 공동 | [제품 문서](product/README.md) |
| Architecture | 시스템 경계와 품질 속성 | 아키텍처·런타임 | [아키텍처 문서](architecture/README.md) |
| Specifications | API와 공유 계약 | 공동 | [명세 문서](specifications/README.md) |
| Operations | 개발, 검증과 운영 | 아키텍처·런타임 | [운영 문서](operations/README.md) |
| Collaboration | 역할, 소유권과 리뷰 방식 | 공동 | [협업 문서](collaboration/README.md) |
| ADR | 중요한 기술 결정과 근거 | 공동 | [ADR 목록](adr/README.md) |
| Archive | 더 이상 유효하지 않은 기록 | 기존 소유자 | [보관 정책](archive/README.md) |

## 상태와 메타데이터

관리 대상 문서는 다음 머리말을 사용한다.

```yaml
---
status: draft | proposed | accepted | deprecated
owner: knowledge-domain | platform-runtime | shared
reviewers: knowledge-domain, platform-runtime
last-reviewed: YYYY-MM-DD
---
```

- `draft`: 작성 중이며 합의되지 않은 내용
- `proposed`: 리뷰를 요청한 제안
- `accepted`: 현재 구현과 의사결정의 기준
- `deprecated`: 더 이상 기준이 아니며 대체 문서를 명시해야 하는 내용

`last-reviewed`는 내용을 마지막으로 실질 검토한 날짜다. 단순 오탈자 수정으로 날짜를
바꾸지 않는다.

## 변경 규칙

- 하나의 PR은 하나의 문서 목적만 다룬다.
- 코드와 외부 동작이 바뀌면 관련 문서를 같은 PR에서 갱신한다.
- 공유 계약, 제품 범위와 아키텍처 변경은 상대 담당자의 승인을 받는다.
- 승인된 ADR은 덮어쓰지 않는다. 새 ADR에서 기존 ADR을 대체한다.
- 규정과 지원 요건은 문서에 복제하지 않고 `knowledge/`의 source ID를 참조한다.
- 링크와 문서 메타데이터는 `python scripts/check_docs.py`로 검사한다.

## 검토 주기

- 변경 시: PR 작성자가 영향 문서를 갱신한다.
- 매월: 각 소유자가 자신의 `accepted` 문서를 빠르게 확인한다.
- 분기별: 공동 리뷰에서 유지, 개정, 폐기 또는 보관을 결정한다.

새 문서는 [일반 문서 템플릿](templates/document.md), 새 기술 결정은
[ADR 템플릿](templates/adr.md)을 복사해 시작한다.
