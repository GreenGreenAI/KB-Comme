---
status: proposed
owner: knowledge-domain
reviewers: platform-runtime
last-reviewed: 2026-07-27
---

# ADR-0019: 규칙팩 승격 게이트와 전문가 검토 정책 분리

- 상태: 제안
- 날짜: 2026-07-27

## 배경

`production_ready=false`는 지금까지 규칙이 아직 검토되지 않았다는 상태와, 보험·법규
판단 특성상 운영 중에도 사람 확인이 필요하다는 정책을 동시에 표현했다. 이 상태에서
검토를 마친 규칙을 `true`로 바꾸면 후보 결과가 사람 검토 없이 자동 확정된 것처럼
표현될 수 있다. 반대로 계속 `false`로 두면 검증 완료 여부를 운영 상태와 구분할 수
없다.

또한 경계 사례와 승인 기록이 코드 밖에 있으면 규칙 조건만 변경하고 정답 사례나
상대 역할 검토를 건너뛸 수 있다.

## 고려한 선택지

1. `production_ready`를 영구적으로 `false`로 둔다. 안전하지만 검증 완료와 미완료를
   구분하지 못한다.
2. 승격 후 모든 일치 결과를 자동 후보로 반환한다. 단순하지만 신고·보험 승인 경계를
   약화한다.
3. 규칙 검증 상태와 결과 검토 정책을 분리하고, 정답 suite와 승인 manifest를 CI에서
   검사한다.

## 결정

선택지 3을 채택한다.

- `production_ready`는 출처·정답 사례·상대 역할·도메인 검토가 완료된 규칙인지
  나타낸다.
- `review_policy=always_expert`는 승격 후에도 일치 결과를
  `expert_confirmation_required`로 유지한다.
- K-SURE와 외국환 규칙은 모두 `always_expert`를 명시한다.
- validation suite는 각 규칙에 대해 일치, 명시적 비일치, 정보 누락을 모두 요구한다.
- 금액 임계값은 JSON 부동소수점이 아니라 decimal 문자열로 고정한다.
- 승인 manifest에는 지식·도메인, 플랫폼·런타임, 도메인 전문가 역할이 모두 필요하다.
- 승인에는 reviewer, timezone이 있는 시각, Git commit, 규칙팩과 validation suite의
  canonical SHA-256을 기록한다. 승인 후 자산이 바뀌면 승인은 stale로 거부한다.
- 모든 승인이 완료되기 전에 `status=active` 또는 `production_ready=true`로 바뀌면
  CI가 실패한다.

## 결과

규칙은 운영 검증을 마쳐도 전문가 확인 정책을 잃지 않는다. 경계값이나 조건 변경은
golden case 차이로 드러나며, 승인받은 파일이 바뀌면 재검토가 필요하다. 현재 두
규칙팩은 golden suite를 통과하지만 세 역할 승인이 없으므로 draft 상태를 유지한다.

## 검증

- 모든 규칙의 true/false/missing 커버리지 검사
- K-SURE 730/731일, 외국환 5천·1만·10만달러 및 365/366일 경계 사례
- 승인 메타데이터·artifact hash 불변식 테스트
- 승인 없는 production flag를 거부하는 회귀 테스트
- `scripts/check_rulepacks.py`를 로컬 check와 CI에서 실행
