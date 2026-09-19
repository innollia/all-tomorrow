# 01C — Durable Execution Bridge

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01B + Stage 0 substrate 채택

## 목적

custom DurableWorkQueue를 만들지 않고 All Tomorrow Work를 Stage 0에서 선택된 durable backend에 연결한다.

이 문서는 backend 선택 전에는 stable port와 cross-store protocol만 확정한다. DBOS/Restate별 concrete mapping은 00E에서 winner에 맞춰 채운다.

## Stable Port

DurableExecutionPort 최소 contract:

- start(work_id, execution_spec, *, idempotency_key, priority, delay)
- get(execution_ref)
- cancel(execution_ref)
- signal(execution_ref, topic, payload)
- result(execution_ref)

필요한 기능만 contract에 올린다. 외부 engine API 전체를 추상화하지 않는다.

## Identity

- Work 1:N Run
- 새 logical attempt는 새 run_id
- run_id는 첫 adapter의 deterministic external execution/idempotency identity 후보
- ExecutionRef는 backend-neutral reference
- external backend status/schema를 Run domain으로 복사하지 않음

## Cross-store start protocol

application DB와 durable backend state 사이에 distributed transaction을 만들지 않는다.

1. Work에 새 Run/ExecutionAttempt를 STARTING으로 application DB transaction에 기록
2. commit
3. 같은 run_id를 deterministic external execution identity로 사용해 start
4. 반환된 handle을 ExecutionRef로 attach
5. crash로 3/4 사이가 끊기면 STARTING + no-ref Run을 scan
6. 같은 run_id로 start/get을 반복해 기존 execution을 회수

이 reconciliation은 external start delivery 복구만 담당한다. queue ordering/lease/retry를 새로 구현하지 않는다.

## scheduler.py

기존 in-memory WorkQueue는 test/prototype로 남길 수 있다.

production용 새 SQL heap/claim/lease/heartbeat/requeue class는 만들지 않는다.

상위 scheduler는 "무슨 Work가 우선인가"라는 semantic policy를 소유하고 selected adapter가 이해하는 priority/delay로 매핑한다.

## Side Effect Rule

durable engine retry가 외부 mutation의 exactly-once를 보장한다고 가정하지 않는다.

worker/tool mutation에는 idempotency key + reconciliation contract를 둔다.

## Stage 0가 채워야 할 항목

00E에서만 다음을 구체화한다.

- selected adapter package
- run_id → external identity mapping
- priority/delay mapping
- user signal mapping
- backend restart semantics
- concurrency/rate-control mapping
- persisted name/versioning constraints
- system-state storage boundary

## 완료조건

1. custom lease/queue recovery code 없음
2. cross-store crash 두 지점 모두 same run_id reconciliation으로 복구
3. 동일 run_id 중복 start가 duplicate execution을 만들지 않음
4. priority/delay가 selected adapter를 통해 동작
5. backend restart 뒤 execution recovery
6. domain package가 selected backend 내부 type을 import하지 않음
