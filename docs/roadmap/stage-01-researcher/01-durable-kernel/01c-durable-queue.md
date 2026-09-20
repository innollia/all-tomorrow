# 01C — Durable Execution Bridge

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01B + Stage 0 substrate 채택
- contracts: ../../domain-contracts.md, ../../failure-recovery-contract.md, ../../plan-verification-contract.md

## 목적

custom DurableWorkQueue를 만들지 않고 Run을 Stage 0 selected durable backend에 연결한다.

## Stable port

00B에서 확정한 DurableExecutionPort contract를 그대로 구현한다.

- start
- get
- cancel
- signal
- result

새 backend 기능이 필요하다는 이유로 port를 vendor API mirror로 확장하지 않는다. 추가 operation은 실제 semantic 필요와 alternate adapter contract를 먼저 증명한다.

## Identity

- Work 1:N Run
- Run = logical attempt
- run_id = deterministic external execution/idempotency identity의 source
- ExecutionRef는 Run 소유
- same run_id recovery는 same logical external execution으로 수렴

## Start protocol

../../failure-recovery-contract.md의 cross-store start/reconciliation을 구현한다.

필수:

1. Run STARTING app commit
2. same run_id external start
3. ExecutionRef attach CAS
4. attach 후 semantic state 전환
5. STARTING/no-ref scan
6. concurrent reconciler lock/revision
7. existing execution recover
8. divergent ref fail closed
9. bounded reconciliation exhaustion 기록

## Selected adapter mapping

00E가 다음 concrete mapping을 채운 뒤에만 구현 시작:

- package/runtime/version
- run_id → external identity
- priority
- delay/timer
- signal + signal dedup identity
- cancel
- result retrieval
- restart/recovery
- concurrency/rate primitive
- persisted names/version constraints
- system-state storage boundary

placeholder가 남아 있으면 01C 시작 불가다.

## Side effects

external mutation은 ../../failure-recovery-contract.md의 세 semantics 중 하나를 선언한다.

- IDEMPOTENT_REPLAY
- RECONCILE_BEFORE_RETRY
- NON_RETRYABLE_AMBIGUOUS

engine replay를 exactly-once effect로 간주하지 않는다.

## scheduler.py

production SQL claim/lease/heartbeat/requeue queue를 만들지 않는다.

상위 policy는 semantic priority/delay만 결정한다.
실행 순서/flow-control은 selected backend adapter에 위임한다.

## Requirement / verification

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 01C-01 | duplicate same run start → execution 1개 | live adapter integration | L1 |
| 01C-02 | commit→start crash reconciliation | real process kill | L2 |
| 01C-03 | start→attach crash reconciliation | real process kill | L2 |
| 01C-04 | concurrent reconciler same ref로 수렴 | concurrent integration | L1 |
| 01C-05 | backend restart 뒤 recovery | live runtime restart | L2 |
| 01C-06 | priority/delay/signal/cancel 실제 mapping | selected adapter integration | L1 |
| 01C-07 | alternate fake adapter가 같은 port contract 통과 | contract suite | L0 |
| 01C-08 | custom lease/recovery daemon 없음 | architecture fitness | L0 |

## 완료조건

위 요구가 모두 통과하고 application DB와 durable state 사이 crash window가 duplicate logical execution 없이 복구되어야 한다.
