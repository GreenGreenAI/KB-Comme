# KB Comme

KB Comme는 수출입 거래의 외화 현금흐름, 자금 공백, 환노출, 금융·보증·보험
지원 후보와 규정 근거를 하나의 케이스 단위로 관리하기 위한 독립 프로젝트입니다.

제품 관점에서는 환위험과 결제일 자금 공백을 함께 분석하고, 결과를 바꾸는 질문부터
금융기관 상담 준비까지 연결하는 수출입금융 의사결정 AI로 정의합니다.

금액과 판정은 결정론적 코드가 만듭니다. 언어모델은 이미 나온 결과를 한국어로
다듬을 뿐이고, 수치를 하나라도 지어내면 그 문장은 통째로 거부되고 코드가 쓴
문장이 나갑니다.

현재 골격은 다음 원칙을 구현합니다.

- 수출과 수입을 별도 제품이 아닌 연결 가능한 현금흐름으로 모델링
- 금액 계산과 조건 판정은 결정론적 코드로 실행
- 모든 제도·규정 판정은 출처, 시행일, 버전이 있는 근거를 요구
- 자료 부족, 만료된 출처, 불확실한 조건은 임의 추론하지 않고 검토 대상으로 전환
- 기존 `hobit-ax-agentos`, `hobit-ax` 코드는 의존하거나 복사하지 않음

## 현재 구현 범위

```text
거래 입력
  → 통화별 현금흐름·자금 공백 분석
  → 지원제도 규칙 후보 판정
  → 출처와 계산 근거 조립
  → Evidence Contract 검증
  → 자동 결과 또는 전문가 검토 전환
```

초기 범위는 거래 실행이나 금융상품 판매가 아니라 의사결정 지원입니다. 샘플
규칙은 구조 검증용이며 실제 신청 자격이나 규제 판단에 사용할 수 없습니다.

## 실행

Python 3.11 이상에서 외부 런타임 의존성 없이 동작합니다.

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python examples/linked_trade_demo.py
```

외부 API를 사용하는 로컬 개발에서는 `.env.example`을 `.env`로 복사해 필요한
값만 채우고, 같은 PowerShell 프로세스에서 먼저 불러옵니다. `.env`와 그 변형은
Git에서 제외되며 실제 키를 `.env.example`에 넣지 않습니다.

```powershell
. .\scripts\import_env.ps1
$env:PYTHONPATH='src'
python -m tradeflow.integration.ecos 20260701 20260729
```

대표 시나리오에서 수입 거래를 추가하면 거래 순노출은 **100,000 → 40,000**으로
줄지만, 수취일보다 지급일이 빨라 **60,000 USD 자금 공백**이 새로 생깁니다.
전체 대본은 [`docs/product/demo-script.md`](docs/product/demo-script.md)에 있습니다.

지원제도 질문에는 기업규모·신용 상태와 규칙이 요구하는 추가 사실을 순서대로
확인해 판정을 닫습니다.

선택 환경변수와 키가 없을 때의 동작은 다음과 같습니다.

| 변수 | 없으면 |
|---|---|
| `UPSTAGE_API_KEY` | 규칙이 조립한 결정론적 문장을 사용합니다 |
| `ECOS_API_KEY` | 커밋된 환율 스냅샷을 사용합니다 |
| `TRADEFLOW_SIGN_IN` | 인증 경로를 닫고 비로그인으로 동작합니다 |

## 주요 디렉터리

- `src/tradeflow/domain`: 거래, 회사, 현금흐름, 판정 모델과 계층 공통 값객체
- `src/tradeflow/contracts`: 두 담당자가 공동 승인하는 안정 인터페이스
- `src/tradeflow/tools`: 결정론적 환노출·자금 공백 계산
- `src/tradeflow/knowledge`: 출처 레지스트리, 규칙 저장소, 조건 평가, 근거 계약
- `src/tradeflow/runtime`: 전체 분석 파이프라인과 검토 게이트
- `src/tradeflow/integration`: 외부 출처 수집기. 다른 모듈이 import하지 않는 리프
- `knowledge`: 출처 및 규칙 팩의 예시 데이터
- `data/snapshots`: 수집된 원본 스냅샷. 재현성을 위해 커밋합니다
- `tests`: 핵심 계산·판정·근거 누락 회귀 테스트
- [`docs`](docs/README.md): 제품, 아키텍처, 명세, 운영과 협업 문서 포털

2인 협업 시 역할과 폴더 소유권은 [OWNERS.md](OWNERS.md), 작업·리뷰 절차는
[CONTRIBUTING.md](CONTRIBUTING.md)를 기준으로 합니다.
