# 03F — Evaluation & Self-Improvement Acceptance

## Status

- 상태: **선행작업 대기**
- 선행조건: 03A~03E 완료
- 지금 시작 가능: **아니오**

## Scenarios

1. 낮은 utility evidence → proposal
2. candidate 생성 전 evaluation criteria freeze
3. sandbox에서 동일 baseline/candidate case set
4. mixed evaluator가 common/dynamic/user evidence 처리
5. candidate가 criteria/fixture 변경 시 reject/protected
6. ordinary prompt/config ACCEPT → promotion
7. ordinary code candidate → versioned deployment + in-flight strategy
8. monitoring hard regression → exact rollback
9. evidence conflict → NEED_MORE_EVIDENCE
10. protected/unknown-impact proposal → APPROVAL_REQUIRED
11. AWS direct protected apply 실패
12. inferred preference가 explicit command를 override하지 않음
13. candidate hash 변경 후 prior evaluation/approval 무효

## Hard completion conditions

- automatic ACCEPT는 frozen criteria policy를 통과해야 함
- production monitoring policy가 명시되지 않은 target은 auto promotion 대상 아님
- code deployment는 L2 이상 in-flight compatibility 증거 필요
- protected path는 04E 실제 authority가 없으면 apply 완료로 간주하지 않음

## 완료 시

03A~03F와 parent 상태를 실제 evidence에 맞게 갱신한다.
