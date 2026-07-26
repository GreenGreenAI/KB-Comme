---
status: accepted
owner: platform-runtime
reviewers: knowledge-domain
last-reviewed: 2026-07-26
---

# 개발과 검증

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
.\scripts\check.ps1
```

검증 명령은 단위·경계 테스트, Python 컴파일과 문서 링크 검사를 실행한다. PR을
요청하기 전에 로컬에서 통과시킨다. 역할별 브랜치와 완료 기준은
[CONTRIBUTING.md](../../CONTRIBUTING.md)를 따른다.
