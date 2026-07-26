# Contributing

## 작업 시작

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
.\scripts\check.ps1
```

브랜치는 `knowledge/<작업명>`, `platform/<작업명>`, `shared/<작업명>` 중 하나를
사용합니다. 하나의 PR에는 한 가지 책임만 포함합니다.

## 완료 기준

- 담당 폴더의 테스트가 추가되거나 갱신됨
- `scripts/check.ps1` 통과
- 출처 기반 변경에는 source ID, 시행일, 확인일이 기록됨
- 계산식 변경에는 입력과 기대 결과가 있는 회귀 테스트가 포함됨
- 불확실한 값이 자동 판정으로 승격되지 않음
- 공유 계약 변경은 상대 담당자의 검토를 받음

## 금지 사항

- 외부 원본 저장소 코드를 TradeFlow로 직접 import
- 출처 없는 규정·지원 요건을 production-ready로 지정
- Knowledge Layer에서 계산 도구나 Runtime을 역참조
- Runtime에서 문장 키워드만으로 자격을 확정
- 실제 비밀값이나 고객 데이터를 저장소에 커밋

