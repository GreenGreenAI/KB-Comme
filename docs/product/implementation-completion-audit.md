---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-29
---

# API 제외 구현 완료 감사

## 감사 기준

- 감사 commit: `018b2c420d31c11e8071c2aed6262c2c075368df`
- 감사 브랜치: `codex/mvp-completion`
- 기준일: 2026-07-29 KST
- 포함: API 연결을 제외하고 2026-07-29까지 남은 것으로 보고한 구현사항
- 제외: 실호가·은행·보험·신고기관 외부 API 계약과 credential, 외부 시스템 제출

`완료`는 파일이 존재한다는 뜻이 아니다. 현재 commit에서 실행되는 구현, 해당
요구사항을 직접 검증하는 테스트와 전체 회귀 결과가 모두 있어야 한다.

## 요구사항별 증거

| 요구사항 | 구현 증거 | 직접 검증 | 판정 |
|---|---|---|---|
| 규칙팩 platform 승인과 변조 방지 승격 | `knowledge/reviews/rulepack_promotion.json`, `validation.rulepack_review_hash`, `scripts/promote_rulepacks.py` | `test_rulepack_activation.py`, `test_rulepack_promotion.py` | 코드 완료 |
| 독립 전문가 답변 수령 계약 | 검토 request 2개, `record_domain_rulepack_review.py`, 독립성·기관·권한·evidence hash 필수 | `test_domain_review_packets.py`, `test_domain_review_recording.py` | 수령 경로 완료, 실제 답변 대기 |
| 재분석 변경 요약과 반복 카드 축소 | `Thread.ResultChangeSummary`, `ResultUpdate` | `Thread.test.jsx` | 완료 |
| 헤지 모델 검증 영속화·3역할 승격 | `hedge_model_promotion.py`, `manage_hedge_model_promotion.py` | `test_hedge_model_promotion.py` | 완료 |
| 운영 중 모델 성능 저하 감지 | `hedge_model_monitoring.py`, `check_hedge_model_drift.py` | `test_hedge_model_monitoring.py` | 완료 |
| 문서 업로드·형식·능동 콘텐츠 검사 | `runtime/documents.py`, `/api/trade-cases/{id}/documents` | `test_documents.py`, `test_document_web.py` | 완료 |
| PDF·이미지 OCR 경계와 fail-closed 상태 | `pypdf`, Tesseract adapter, `needs_ocr` | 텍스트 PDF 경계와 주입 OCR 계약 테스트 | 완료 |
| 추출값·원문 위치·신뢰도·사용자 확인 | extraction schema와 confirm-fields endpoint/UI | runtime·HTTP·React 문서 테스트 | 완료 |
| 거래·문서·신용장 불일치 | `check_case`, document-check endpoint/UI | 문서 간·거래 대비 mismatch와 L/C 필드 테스트 | 완료 |
| 원본 암호화와 tenant 격리 | AES-256-GCM, organization AAD, tenant 조건 조회 | 암호문 평문 부재, cross-tenant 404, PostgreSQL 문서 테스트 | 완료 |
| 운영 PostgreSQL | `PostgresAccountStore`, `PostgresTradeDocumentStore`, 운영 SQLite 거부 | PostgreSQL 16 실제 컨테이너 통합 테스트, CI service | 완료 |
| 조직 RBAC | account/organization 분리와 role permission matrix | 조직 내 공유·조직 간 차단·RM 기본 차단 테스트 | 완료 |
| 세션·로그인 보호 | DB token hash, 만료·로그아웃, 5회 실패 잠금 | `test_accounts.py` | 완료 |
| 감사 이력 | tenant별 append-only hash chain, DB UPDATE/DELETE trigger | SQLite·PostgreSQL chain/immutability 테스트 | 완료 |
| HTTP 보안 경계 | Origin allowlist, CSP, frame·MIME·referrer·permission headers | `test_security_boundary.py` | 완료 |
| 문서 Workspace | 업로드, 필드 수정·확인, 정합성 결과 | `DocumentPanel.test.jsx`, signed-in Playwright E2E | 완료 |
| 커밋·원격 반영 | `734d25d`, `8ddee4d`, `018b2c4` | local/remote rev-list `0 0`, clean worktree | 완료 |

## 2026-07-29 재현 결과

PostgreSQL 16 임시 컨테이너를 포함해 현재 commit에서 실행했다.

```text
python -W error::DeprecationWarning -m unittest discover -s tests -t .
Ran 561 tests in 20.788s — OK

npm test
4 files, 11 tests — passed

npm run build
38 modules transformed — passed

npm run test:e2e
2 tests — passed

python scripts/check_docs.py
Documentation checks passed (63 files)
```

`python scripts/check_rulepacks.py`의 두 규칙팩은 validation·integrity 오류가 없다.
각 규칙팩에 남은 blocker는 동일하다.

```text
pending approval: domain_expert
rules remain production_ready=false
rulepack status is not active
```

뒤의 두 항목은 첫 항목을 우회하지 못하게 하는 파생 안전장치다. 독립 전문가 승인
없이 제거하거나 `active`로 바꾸는 것은 완료가 아니라 정책 위반이다.

## 유일한 외부 완료 조건

다음 두 패킷에 대해 규칙 작성자와 독립적인 전문가의 실제 답변이 필요하다.

- `knowledge/reviews/requests/ksure_mvp_candidates_review_request.json`
- `knowledge/reviews/requests/fx_compliance_mvp_review_request.json`

답변 원문은 저장소 밖 tenant-private 위치에 두고 다음 순서로 처리한다.

1. `record_domain_rulepack_review.py`로 reviewer, organization, authority basis와 원문
   hash를 기록한다.
2. `check_rulepacks.py`로 승인 hash와 validation suite를 다시 검증한다.
3. 두 pack을 `promote_rulepacks.py`로 각각 원자적 승격한다.
4. `check_rulepacks.py --require-ready`와 전체 회귀 테스트를 실행한다.
5. 승격 commit을 상대 역할이 검토한 뒤 병합한다.

전문가의 신원·소속·권한 근거와 원문 증거를 KB Comme 작성자가 대신 만들어서는
안 된다. 따라서 이 한 항목은 코드 작업으로 대체할 수 없는 외부 운영 게이트다.
