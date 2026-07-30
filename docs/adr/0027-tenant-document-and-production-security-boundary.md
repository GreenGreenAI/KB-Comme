---
status: proposed
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-29
---

# ADR-0027: tenant 문서와 운영 보안 경계

- 상태: 제안
- 날짜: 2026-07-29
- 관련: ADR-0026, 제품 아키텍처 §11.7, §16

## 배경

ADR-0026은 문서 암호화와 보존정책이 없다는 이유로 원본 문서 저장을 범위 밖에
두었다. Phase 4에서 계약서·신용장·Invoice의 추출값을 거래와 비교하려면 원본,
추출값, 원문 위치, 확인자를 한 tenant 안에서 연결해야 한다. 동시에 로컬 SQLite,
평문 세션 토큰, 역할 구분 없는 계정으로는 운영 고객 문서를 받을 수 없다.

## 결정

1. 개발은 SQLite, 운영은 PostgreSQL을 사용한다. `TRADEFLOW_ENV=production`인데
   `TRADEFLOW_DATABASE_URL`이 없으면 애플리케이션은 시작하지 않는다.
2. 계정과 회사 tenant를 분리한다. 여러 계정이 하나의 `organization_id`를 공유할
   수 있고 모든 분석·문서 조회는 조직 조건을 포함한다.
3. `company_user`, `company_admin`, `rm`, `data_admin`,
   `operations_admin` 역할을 최소 권한으로 고정한다. RM·운영·데이터 역할은 역할명
   자체만으로 고객 데이터를 읽을 수 없다.
4. 세션 원문은 쿠키로 한 번만 전달하고 DB에는 SHA-256 키만 저장한다. 반복 로그인
   실패는 같은 식별자 hash 기준으로 제한한다.
5. 문서 원본은 tenant·case·document ID를 AAD로 사용하는 AES-256-GCM으로 암호화한다.
   운영 키는 환경의 secret manager에서만 주입한다.
6. 업로드는 크기, 확장자, MIME, 파일 signature, 실행·능동 콘텐츠 표지를 검사한다.
   텍스트가 없는 PDF·이미지는 OCR 완료로 가장하지 않고 `needs_ocr`로 둔다.
7. 추출 필드는 값, 정규화 값, 원문 page/line 위치, 신뢰도와 사용자 확인 기록을
   함께 보존한다. 확인 전 값은 거래 사실로 승격하지 않는다.
8. 로그인, 분석, 문서 열람·업로드·확인·정합성 검사, 권한 거부는 tenant별
   append-only hash chain에 기록한다. 감사 행의 UPDATE·DELETE는 DB trigger가
   거부한다.
9. 상태 변경 요청의 Origin을 allowlist로 검사하고 CSP, frame 차단, MIME sniffing
   방지, referrer·browser permission 제한 헤더를 응답에 적용한다.

## 결과

- PostgreSQL 계정·세션·분석·감사 저장소와 문서 메타데이터 저장소는 동일 계약으로
  동작하며 실제 PostgreSQL 통합 테스트를 CI에서 실행한다.
- 문서 원본은 Git과 공개 snapshot에 들어가지 않는다.
- 다른 조직의 document/run ID는 존재 여부를 드러내지 않고 `404`가 된다.
- 불일치와 신용장 필수 필드 누락은 자동 수정되지 않고 `review_required`가 된다.
- 독립 악성코드 엔진이나 OCR 실행 환경이 없을 때 시스템은 검사를 수행한 것처럼
  표시하지 않는다. 운영 배포 요건은 별도 런북에서 확인한다.

## 검증

- SQLite와 PostgreSQL에서 조직 내 공유·조직 간 격리 테스트
- DB에 세션 원문이 남지 않는 테스트
- 감사 hash chain 및 UPDATE 거부 테스트
- 암호문에 원문 문자열이 나타나지 않는 테스트
- 문서 형식·능동 콘텐츠·추출·확인·불일치 테스트
- 허용되지 않은 Origin 및 보안 응답 헤더 테스트
- React 문서 업로드·확인·정합성 UI 테스트
