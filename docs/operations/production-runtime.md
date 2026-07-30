---
status: accepted
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-29
---

# 운영 런타임과 복구

## 필수 구성

운영 프로세스는 다음 값을 secret manager 또는 배포 환경에서 주입한다.

| 변수 | 요구사항 |
|---|---|
| `TRADEFLOW_ENV` | `production` |
| `TRADEFLOW_DATABASE_URL` | TLS를 강제하는 PostgreSQL 접속 문자열 |
| `TRADEFLOW_DOCUMENT_KEY` | 무작위 32바이트 키의 표준 Base64 |
| `TRADEFLOW_DOCUMENT_ROOT` | 고객별 접근이 차단된 영속 private volume |
| `TRADEFLOW_ALLOWED_ORIGINS` | 실제 HTTPS 서비스 origin의 쉼표 구분 allowlist |
| `TRADEFLOW_CLAMSCAN_PATH` | 운영 이미지의 검증된 `clamscan` 실행 파일 절대경로 |
| `TRADEFLOW_TESSERACT_CMD` | 한국어·영어 data가 설치된 Tesseract 실행 파일 절대경로 |
| `TRADEFLOW_SECURE_COOKIE` | 비어 있지 않은 값 |
| `UPSTAGE_API_KEY` | LLM 설명 기능을 사용할 때만 설정 |

운영 모드에서 PostgreSQL URL, 문서 키, ClamAV 또는 Tesseract 경로가 없으면 시작이 실패한다. 로컬
`data/accounts.db`와 `data/.document-key`는 개발 전용이며 운영 fallback이 아니다.

문서 키를 바꾸면 기존 암호문을 읽을 수 없으므로 즉시 덮어쓰지 않는다. 별도
key-version migration으로 복호화·재암호화하고 복구 검증 후 이전 키를 폐기한다.

## PostgreSQL

애플리케이션은 시작 시 idempotent schema를 확인한다. CI는 PostgreSQL 16 컨테이너에서
계정, 조직 공유, 세션, 분석 이력, 감사 hash chain과 문서 메타데이터 계약을 실행한다.
운영 DB 계정은 애플리케이션 schema에만 권한을 가지며 superuser를 사용하지 않는다.

백업 예:

```powershell
pg_dump --format=custom --no-owner --file tradeflow.dump $env:TRADEFLOW_DATABASE_URL
```

문서 private volume은 DB dump와 같은 복구 시점으로 암호화 백업한다. DB만 복구하면
metadata가 가리키는 암호문이 없고, volume만 복구하면 tenant·AAD 연결을 확인할 수
없으므로 둘은 한 복구 세트다.

복구 훈련에서는 별도 격리 환경에 DB와 volume을 복원한 뒤 다음을 확인한다.

1. `/api/health`가 snapshot과 PostgreSQL backend를 보고한다.
2. 서로 다른 두 tenant가 상대 분석·문서를 읽지 못한다.
3. `GET /api/audit-events`의 `chain_valid`가 `true`다.
4. 표본 암호문을 승인된 키로 복호화할 수 있고 content hash가 metadata와 같다.
5. 복구 환경의 세션을 모두 폐기하고 새 세션으로만 접근한다.

## OCR과 악성코드 검사

- 텍스트 PDF는 `pypdf`, 이미지는 승인된 Tesseract 설치를 통해 추출한다.
- Tesseract가 없거나 텍스트를 얻지 못하면 상태는 `needs_ocr`이며 필드를 만들지
  않는다.
- 내장 검사는 파일 signature, 크기, MIME 불일치, 실행 파일과 PDF 능동 콘텐츠를
  fail-closed로 차단한다.
- 운영 업로드는 shell을 거치지 않고 설정된 `clamscan`을 실행하며, 감염 발견뿐
  아니라 scanner 자체의 오류·시간초과도 업로드 실패로 처리한다. 고위험 환경에서는
  별도 격리 CDR scanner를 추가하고 두 검사를 혼동하지 않는다.

## 보안 운영

- 로그인 15분 창에서 5회 실패하면 15분 동안 잠긴다. 계정 존재 여부와 잠금 여부는
  동일한 오류로 응답한다.
- DB에는 세션 원문 대신 hash만 저장한다.
- 고객 데이터 권한 거부도 감사 이벤트로 남는다.
- `rm`, `data_admin`, `operations_admin`은 고객 조직 할당 없이 고객 분석·문서를
  열람할 수 없다.
- 허용 origin, TLS·secure cookie와 CSP 설정은 배포 smoke test에서 확인한다.
- 감사 테이블 변경 권한과 문서 volume 직접 접근 권한은 애플리케이션 운영자에게도
  상시 부여하지 않는다.
