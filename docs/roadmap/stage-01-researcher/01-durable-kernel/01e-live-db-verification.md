# 01E — Live Failure Verification

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A~01D
- contracts: ../../plan-verification-contract.md, ../../failure-recovery-contract.md

## 목적

실제 PostgreSQL + selected durable backend에서 01A~01D 경계를 재현 가능한 acceptance로 증명한다.

## Environment

- application/domain PostgreSQL
- selected durable backend state/runtime
- 별도 application process
- 필요한 gateway/worker fixture

동일 PostgreSQL server를 쓸 수 있지만 schema/database ownership은 분리한다.

## Scenarios

| ID | 시나리오 | 핵심 증거 | Level |
|---|---|---|---|
| 01E-01 | 기존 migration chain | pre/post identity/data 보존 | L1 |
| 01E-02 | Goal/Work/Run 저장 후 app restart | same ids/revisions | L2 |
| 01E-03 | Run commit 후 start 전 kill | same run_id, execution 1개 | L2 |
| 01E-04 | external start 후 ref attach 전 kill | existing execution 회수 | L2 |
| 01E-05 | same run_id concurrent start | logical execution 1개 | L1/L2 |
| 01E-06 | priority/delay | selected backend 실제 ordering/timer evidence | L1 |
| 01E-07 | model/tool 사이 process kill | same Run resume | L2 |
| 01E-08 | NEED_USER wait restart/answer | question 1개, signal dedup | L2 |
| 01E-09 | mutation commit 후 kill | applied effect semantics 준수 | L2 |
| 01E-10 | Work→multiple Run lineage | refs/provenance 보존 | L1 |
| 01E-11 | Event/audit retention | run cleanup에도 event 보존 | L1 |
| 01E-12 | OTel correlation | work/run/execution/tool ids 연결 | L1 |
| 01E-13 | V1 in-flight → V2 | 00E upgrade strategy 실제 통과 | L2 |
| 01E-14 | concurrent reconciliation | divergent attach 없음 | L1 |
| 01E-15 | backend unavailable/unknown effect | fabricated success 없음 | L1 |

각 crash scenario는 actual child process kill을 사용한다.

## Backend escape

fake/alternate adapter가 DurableExecutionPort contract suite를 통과해야 한다.
production으로 두 번째 backend를 배포할 필요는 없지만 selected backend internal type이 domain에 새지 않았음을 검증한다.

## Wrong-implementation negatives

최소:

- Work에 단일 ExecutionRef를 붙인 schema가 architecture test 실패
- duplicate effect fixture가 acceptance 실패
- exception-only crash가 L2 gate를 충족하지 못함
- different ExecutionRef CAS overwrite 실패
- caller가 original correlation을 재주입해도 persistence 검증을 우회하지 못함

## 완료조건

01E-01~15가 요구 level에서 모두 통과하고 전체 regression suite도 통과해야 01 parent를 개발완료로 올릴 수 있다.
