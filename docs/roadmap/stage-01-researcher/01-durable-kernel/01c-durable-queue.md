# 01C — Durable Execution Bridge

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01B + Stage 0 substrate 채택

## 목적

custom DurableWorkQueue를 만들지 않고 All Tomorrow Work를 durable backend에 연결한다.

Stage 0 primary가 통과하면 첫 구현은 DBOS다.

## Stable Port

DurableExecutionPort 최소 contract:

- start(work_id, execution_spec, *, idempotency_key, priority, delay)
- get(execution_ref)
- cancel(execution_ref)
- signal(execution_ref, topic, payload)
- result(execution_ref)

필요한 기능만 contract에 올린다. DBOS API 전체를 추상화하지 않는다.

## DBOS adapter

초기 매핑:

- All Tomorrow run_id → DBOS workflow id
- Work 1:N Run 구조로 새 logical attempt는 새 run_id를 가짐
- P0~P6 → DBOS priority mapping
- not-before 요구 → enqueue delay
- duplicate ingress → deduplication/return-existing
- user response → durable message/event
- crash/restart → DBOS recovery
- concurrency/rate → DBOS queue configuration

DBOS system DB는 application DB 정본과 논리적으로 분리한다.

## Cross-store start protocol

DBOS system DB와 application DB 사이의 distributed transaction은 만들지 않는다.

1. Work에 새 Run/ExecutionAttempt를 STARTING 상태로 application DB transaction에 기록
2. commit 후 run_id를 deterministic workflow ID로 사용해 start/enqueue
3. DBOS가 반환한 handle을 ExecutionRef로 attach
4. crash로 2/3 사이가 끊기면 STARTING + no-ref Run을 scan해 같은 run_id로 다시 start
5. DBOS의 workflow-ID idempotency로 기존 execution handle을 회수

reconciliation scan은 external start delivery 복구만 담당한다. queue ordering/lease/retry를 구현하지 않는다.

## scheduler.py

기존 in-memory WorkQueue는 test/prototype로 남길 수 있다.

production durable queue를 대체하는 새 SQL heap/lease class는 만들지 않는다.

상위 scheduler는 "무슨 Work가 우선인가"를 결정하고 adapter에 enqueue parameter를 준다.

## Side Effect Rule

durable engine이 재시도한다고 모든 외부 mutation이 자동으로 안전해지는 것은 아니다.

worker/tool mutation에는 별도 idempotency/reconciliation contract를 유지한다.

## 완료조건

1. custom lease code 없음
2. cross-store crash 두 지점 모두 same run_id reconciliation으로 복구
3. 동일 run_id 중복 start가 duplicate execution을 만들지 않음
4. priority/delay가 adapter를 통해 동작
5. backend restart 뒤 execution recovery
6. domain package가 DBOS 내부 type을 import하지 않음
