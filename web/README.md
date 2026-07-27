# 웹 앱 실행

대화형 분석 화면입니다. 서버는 FastAPI, 화면은 React이며 둘 다 이 저장소 안에
있습니다.

**LLM API 키 없이 전 구간이 동작합니다.** 되묻기, 노출·변동성·헤지 계산, 결과
표시까지 모두 결정론적 코드가 수행하기 때문입니다. 키는 응답의 `summary` 문장을
생성할 때만 필요하며, 그때까지 이 필드는 비어 있습니다.

## 준비

```bash
python -m venv .venv
.venv/bin/pip install -e '.[app]'
```

```bash
cd web/frontend
npm install
npm run build
```

> **macOS 주의 — `node`가 어느 것인지 확인하십시오.**
> `Codex.app`이나 다른 앱 번들 안의 `node`가 `PATH` 앞에 있으면 프런트엔드
> 빌드가 실패합니다. 앱 번들은 서명된 프로세스라 서드파티 네이티브 모듈을
> 적재하지 못하고, `rollup`이 다음과 같이 끊깁니다.
>
> ```
> code signature ... not valid for use in process:
> mapping process and mapped file (non-platform) have different Team IDs
> ```
>
> 확인과 해결:
>
> ```bash
> which node                      # /Applications/... 이면 문제
> export PATH="/opt/homebrew/bin:$PATH"
> ```

## 실행

```bash
.venv/bin/python -m uvicorn tradeflow.web.app:app --port 8000
```

http://127.0.0.1:8000 에서 열립니다. 서버가 API와 빌드된 화면을 함께 제공합니다.

### 화면을 고치며 작업할 때

빌드를 매번 돌리지 않으려면 개발 서버를 함께 띄웁니다. Vite가 `/api` 요청을
uvicorn으로 넘겨주므로 브라우저에서는 한 곳으로 보입니다.

```bash
.venv/bin/python -m uvicorn tradeflow.web.app:app --port 8000   # 터미널 1
cd web/frontend && npm run dev                                   # 터미널 2
```

## 확인해 볼 것

앱이 제대로 도는지는 다음 순서로 보면 한 번에 드러납니다.

1. **진입 화면에서 칩 하나를 누릅니다** — 예: `10월 24일에 수출대금 10만 달러
   받기로 했어요`. 문장에서 방향·금액·날짜를 뽑아 바로 계산합니다.
2. **대화에 도구 실행 흔적이 남는지** 봅니다. `✓ 순노출·자금공백 산출`처럼
   무엇이 실제로 계산됐는지 표시됩니다.
3. **패널이 `2 / 5 완료`인지** 봅니다. 잠긴 섹션은 무엇을 알려주면 열리는지
   스스로 말합니다.
4. **영업이익을 입력합니다** — 예: `6000000`. `3 / 5`로 오르고 손익·헤지
   섹션이 열리며, 손익분기 환율이 밴드 위에 나타납니다.
5. **불완전한 문장을 넣어 봅니다** — 예: `수출대금 받을 예정이에요`. 금액과
   날짜를 되묻고, 추정해서 채우지 않습니다.

### 워커 실패를 직접 보려면

스냅샷을 잠시 옮기면 환율 워커만 실패하고 나머지는 살아남습니다 (§9.3).

```bash
mv data/snapshots/ECOS_USD_KRW /tmp/snapshot-away
# 분석을 실행하면 노출은 계산되고, 시장·헤지는 빠진 채 사유가 표시됩니다
mv /tmp/snapshot-away data/snapshots/ECOS_USD_KRW
```

## API만 확인할 때

```bash
curl -s localhost:8000/api/health

curl -s localhost:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"utterance":"10월 24일에 수출대금 10만 달러 받아요","baseline_profit":"6000000"}'
```

응답은 `status`가 `needs_input`이면 되물을 질문을, `ready`면 §7 응답 계약을
담습니다.

## 아직 없는 것

- **LLM 합성** — `summary`는 비어 있고 에이전트 문구는 규칙 기반입니다
- **인증** — 네비의 로그인·프로필은 화면만 있고 실제 인증은 없습니다
- **지원제도·신고의무 판정** — 역할 A가 작업 중이며, 연결 전까지 패널에
  "연결 예정"으로 표시됩니다
