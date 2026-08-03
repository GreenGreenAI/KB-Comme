# KB Comme

수출입 거래의 **결제일 자금 공백과 환노출을 함께 계산하고**, 지원제도 자격과
외국환거래법 신고의무를 **출처가 있는 규칙으로 판정**하는 의사결정 지원
프로젝트입니다.

금액과 판정은 결정론적 코드가 만듭니다. 언어모델은 이미 나온 결과를 한국어로
다듬을 뿐이고, 수치를 하나라도 지어내면 그 문장은 통째로 거부되고 코드가 쓴
문장이 나갑니다.

- 수출과 수입을 별도 제품이 아닌 **연결된 현금흐름**으로 모델링
- 모든 제도·규정 판정은 출처, 시행일, 버전이 있는 근거를 요구
- 자료 부족·만료된 출처·불확실한 조건은 추론하지 않고 **검토 대상으로 전환**
- 같은 입력·규칙·데이터 버전은 **같은 결정 패킷**을 재현 (§6.2)

샘플 규칙은 구조 검증용 초안이며 실제 신청 자격이나 규제 판단에 사용할 수
없습니다.

## 요구환경

| | 버전 | 확인된 환경 | 필요한 때 |
|---|---|---|---|
| Python | 3.11 이상 | 3.14.6 | 항상 |
| Node.js | 20 이상 | 24.14.0 | 화면을 **고칠 때만** |

API 키는 **없어도 됩니다.** 아래 모든 명령이 키 없이 그대로 동작합니다.

## 빠른 시작 — Python만 있으면 됩니다

```bash
git clone <repository> tradeflow && cd tradeflow

python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[app]"

PYTHONPATH=src python -m uvicorn tradeflow.web.app:app --port 8000
```

브라우저에서 **http://localhost:8000** 을 엽니다. 서버 하나가 API와 화면을 함께
서빙합니다.

빌드된 화면(`web/frontend/dist`)은 저장소에 함께 들어 있습니다. Node를 설치하고
번들을 만드는 단계 없이 바로 열리도록 한 것이고, 화면 소스를 고쳤을 때만 다시
만들면 됩니다.

```bash
cd web/frontend && npm ci && npm run build    # 고친 뒤 dist를 다시 만듭니다
cd web/frontend && npm run dev                # 고치면서 볼 때. localhost:5173
```

## 데모 입력

화면 하단 예시를 누르거나 그대로 입력하세요.

```text
8월 25일 수입 6만 달러 결제하고 12월 3일 수출 10만 달러 받아요
```

기대 결과입니다. 명세 §5.2의 기준 시나리오와 같은 값입니다.

| | 값 | 뜻 |
|---|---|---|
| 거래 순노출 | **+40,000 USD** | 거래로 생기는 노출(Σ수취 − Σ지급). 받을 돈이 많으므로 원화 강세에 손해 |
| 자금 공백 | **60,000 USD** | 8월 결제일에 모자라는 외화 |
| 기간 상쇄 | **60,000 USD** | 전 기간으로는 상쇄되는 몫 |
| 실제로 덮이는 금액 | **0** | 수취가 지급보다 늦어 자금으로는 덮이지 않음 |

한 문장을 더하면 숫자가 어떻게 움직이는지가 이 제품의 요점입니다.

```text
8월 25일에 수입대금 6만 달러도 나가요
```

거래 순노출은 **100,000 → 40,000**으로 줄고(환율 영향 10,271,000원 → 4,108,400원),
그 대신 8월에 없던 **자금 공백 60,000 USD**가 생깁니다. 총액만 보면 좋아졌고
시점을 보면 부담이 생긴 것이라, 두 숫자를 함께 세는 이유가 여기서 드러납니다.
전체 대본은 [`docs/product/demo-script.md`](docs/product/demo-script.md)에 있습니다.

이어서 「받을 수 있는 지원제도가 있나요」를 물으면 기업규모와 신용 상태를 되묻고,
답하면 K-SURE 세 제도를 판정합니다. 규칙이 더 필요한 사실을 이름으로 물어보므로
(K-SURE 등급, 자금 용도, 선적일) 답할수록 판정이 닫힙니다.

「왜?」라고 물으면 각 판정이 무엇을 확인했는지 말합니다.

curl로 같은 결과를 볼 수도 있습니다.

```bash
curl -s -X POST http://localhost:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"cases":[{"direction":"수입","amount":"60000","expected_payment_date":"2026-08-25"},
                {"direction":"수출","amount":"100000","expected_payment_date":"2026-10-24"}],
       "utterance":"자금이 얼마나 부족한가요","as_of":"2026-08-01"}'
```

## 테스트

```bash
PYTHONPATH=src python -m unittest discover -s tests -q       # 686개
cd web/frontend && npm test                                  # 12개
```

계산·규칙 계층은 **의존성 없이** 돕니다. `pip install` 없이 위 명령을 돌리면
웹 계층 시험 3개만 건너뛰고 **628개**가 통과합니다 — 도메인·도구·지식 계층이
외부 패키지를 부르지 않는다는 것이 시험으로 확인됩니다(ADR-0003).

수용 현황은 별도 보고서로 봅니다.

```bash
PYTHONPATH=src python scripts/acceptance.py
```

```text
시나리오 수용 현황 — 17/22
라우팅 바닥 — 5/5
주제 읽기 — 모델 없음 (UPSTAGE_API_KEY)      # 키가 있으면 11/11
```

한 문장이 계층을 어떻게 지나가는지 보려면:

```bash
PYTHONPATH=src python scripts/trace.py "8월 25일 수입 6만 달러를 상계로 처리하는데 신고 대상인가요"
```

## 환경변수

전부 선택입니다. [`.env.example`](.env.example)을 `.env`로 복사해 채우면 됩니다.

| 변수 | 없으면 |
|---|---|
| `UPSTAGE_API_KEY` | 답변 합성이 물러나고 규칙이 조립한 문장이 그대로 나갑니다. **수치와 판정은 동일합니다** |
| `ECOS_API_KEY` | 커밋된 환율 스냅샷으로 계산합니다. 갱신할 때만 필요합니다 |
| `TRADEFLOW_SIGN_IN` | 인증 경로가 닫히고 비로그인으로 동작합니다 |

## 주요 디렉터리

- `src/tradeflow/domain`: 거래, 회사, 현금흐름, 판정 모델과 계층 공통 값객체
- `src/tradeflow/contracts`: 두 담당자가 공동 승인하는 안정 인터페이스
- `src/tradeflow/tools`: 결정론적 환노출·자금 공백 계산과 발화 읽기
- `src/tradeflow/knowledge`: 출처 레지스트리, 규칙 저장소, 조건 평가, 근거 계약
- `src/tradeflow/agent`: 인테이크, 워커 라우팅, 부분 실패 격리
- `src/tradeflow/runtime`: 분석 파이프라인, 검토 게이트, 답변 조립과 합성 검사
- `src/tradeflow/web`: HTTP 표면. 무상태이며 대화는 브라우저가 들고 있습니다
- `src/tradeflow/integration`: 외부 출처 수집기. 다른 모듈이 import하지 않는 리프
- `web/frontend`: 단일 화면 React 앱
- `knowledge`: 출처 및 규칙 팩
- `data/snapshots`: 수집된 원본 스냅샷. 재현성을 위해 커밋합니다
- `tests`: 계산·판정·근거·계층 경계 회귀 시험
- [`docs`](docs/README.md): 제품, 아키텍처, 명세, 운영과 협업 문서 포털

계층 사이의 의존 방향은 `tests/architecture/test_module_boundaries.py`가 AST로
강제합니다. `integration`은 아무도 import하지 않는 리프이고, 그 밖의 금지된
방향도 같은 파일에 적혀 있습니다.

2인 협업 시 역할과 폴더 소유권은 [OWNERS.md](OWNERS.md), 작업·리뷰 절차는
[CONTRIBUTING.md](CONTRIBUTING.md)를 기준으로 합니다.
