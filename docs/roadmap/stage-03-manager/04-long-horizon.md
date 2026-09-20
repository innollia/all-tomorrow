# Stage 3.4 — Long-Horizon Autonomous Production

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 3.2 + 3.3
- 지금 시작 가능: **아니오**

## 목적

며칠 이상 지속되는 Goal을 dynamic Work graph, artifact milestones, resource budgets, user feedback checkpoint로 실제 완성까지 운영한다.

## Representative target

game demo는 대표 acceptance workload이며 유일한 domain은 아니다.

## Work graph semantics

Goal 아래 Work graph는 dynamic DAG를 기본으로 한다.

Work relation:

- parent/child lineage
- depends_on
- blocks
- supersedes
- generated_by

제약:

- dependency cycle 생성 reject
- dependency terminal state가 downstream activation에 미치는 policy 명시
- failed dependency는 dependent Work를 자동 성공/실패로 위조하지 않고 BLOCKED/WAITING/replan candidate
- dynamic child 생성도 lineage/budget/dedup 적용
- graph 자체를 backend workflow internal graph와 동일시하지 않음

BLOCKED가 canonical Work enum에 필요하면 Stage 3 schema change로 명시적으로 추가하거나 wait_reason dependency로 표현하는 결정을 이 packet 시작 전에 확정한다.

## Milestones / progress

"agent가 많이 실행됨"을 progress로 보지 않는다.

각 long-horizon Goal은 시작 시 versioned milestone/evaluation plan을 가진다.

예 game demo:

- executable/build artifact
- smoke launch
- representative interaction/play path
- automated/manual test evidence
- known issue count/severity
- user feedback checkpoint

progress는 milestone state + immutable ArtifactRefs + test/evaluation evidence로 측정한다.
파일 수/토큰/Work count는 activity metric일 뿐 outcome metric이 아니다.

## Artifact/version management

- source commit/ref
- build artifact hash
- asset/source licenses/provenance
- design/spec versions
- test results
- supersedes links

large artifact는 ArtifactRef contract.

## Checkpoint/resume

multi-day state는 chat transcript에 의존하지 않는다.

resume ContextPack:

- Goal objective/constraints
- graph/open Work
- accepted decisions
- current milestone
- latest artifacts/build/test refs
- unresolved questions
- resource/budget status

restart/resource switch에도 재구성 가능해야 한다.

## User feedback checkpoint

feedback:

- exact artifact/build version
- user instruction/feedback ref
- evaluation interpretation
- generated successor Work refs

inferred preference가 explicit feedback을 대체하지 않는다.

## Resource changes

executor/model offline, quota exhaustion, provider change:

- active external effect ambiguity 먼저 reconciliation
- eligible alternate resource 선택
- new Run provenance
- milestone/Goal identity 유지

## Self-improvement at scale

cross-project evidence도 Stage 1 frozen-eval/protection rail을 유지한다.
더 많은 evidence가 protected boundary를 약화시키는 근거가 되지 않는다.

## Requirements

| ID | 요구 | Level |
|---|---|
| 3.4-01 dynamic graph cycle/replan semantics | L1 |
| 3.4-02 multi-day/restart ContextPack resume | L2/L3 |
| 3.4-03 artifact milestone 실제 진전 | L1/L3 |
| 3.4-04 resource failure → new Run, same Goal | L2 |
| 3.4-05 user feedback → exact artifact-bound follow-up | L1 |
| 3.4-06 budget/dedup prevents graph storm | L1 |
| 3.4-07 representative demo produces runnable/playable artifact | L3 |

## 완료조건

장기 Goal이 activity가 아니라 milestone Artifact/test evidence를 실제로 진전시키며 여러 날의 restart/resource 변화 후에도 같은 objective와 provenance로 이어져야 한다.
