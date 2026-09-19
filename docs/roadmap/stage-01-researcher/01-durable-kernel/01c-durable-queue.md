# 01C — Durable Queue and Lease

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A + 01B 완료
- 완료 후 열림: 01E Live DB Verification

## 목적

현재 메모리 전용 `scheduler.WorkQueue`를 production durable queue로 사용하지 않고 PostgreSQL Work row 자체를 queue authority로 만든다.

## 수정 파일

- 수정: `src/all_tomorrow/scheduler.py`
- 수정: `src/all_tomorrow/storage/work_store.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 수정: `tests/test_scheduler.py`
- 보강: `tests/test_postgres_store.py`

## 기존 WorkQueue 처리

현재 `WorkQueue`는 unit-test용 cooperative in-memory queue로 유지한다.

이름을 당장 깨지 말고 docstring에 prototype/in-memory임을 명시한다.

production path용 새 class:

`DurableWorkQueue`

이 class는 heap을 소유하지 않고 `WorkStateStore`에 위임한다.

## Store method

01B의 Protocol에 추가:

- `enqueue_work(work)` — 내부적으로 create_work 또는 명시적 alias
- `claim_next_work(executor_id, *, lease_seconds, now=None)`
- `heartbeat_work(work_id, executor_id, *, lease_seconds, expected_revision)`
- `complete_work(work_id, executor_id, expected_revision, event)`
- `fail_work(work_id, executor_id, expected_revision, event, *, retry_at=None)`
- `requeue_expired_work(*, now=None, limit=...)`
- `has_higher_priority_pending(priority, *, now=None)`

## claim SQL

한 transaction:

1. status=PENDING
2. `not_before IS NULL OR not_before <= now()`
3. claim 가능한 row를 `FOR UPDATE SKIP LOCKED`
4. `ORDER BY priority ASC, created_at ASC, work_id ASC`
5. 하나 선택
6. status=RUNNING
7. claimed_by=executor_id
8. lease_expires_at=now + lease
9. attempt_count += 1
10. revision += 1
11. `work.claimed` Event append
12. updated Work 반환

두 executor가 같은 Work를 claim하지 못해야 한다.

## heartbeat

다음 조건을 모두 만족할 때만 lease 연장:

- work_id 일치
- status=RUNNING
- claimed_by=executor_id
- revision 일치

claim owner가 아닌 executor heartbeat는 실패 closed.

## expired lease recovery

`requeue_expired_work`:

- RUNNING
- lease_expires_at < now
- PENDING으로 되돌림
- claimed_by/lease clear
- wait_reason clear
- revision 증가
- `work.lease_expired` Event

실행 중 외부 mutation의 side effect가 불명확한 Work를 무조건 재실행하는 정책은 여기서 만들지 않는다. 그런 Work는 payload/metadata의 retry safety를 읽어 WAITING/reconciliation으로 보내는 상위 정책 대상이다.

이번 packet은 queue primitive만 만든다.

## Priority / yield

기존 `Priority` enum 유지.

`DurableWorkQueue.should_yield(current_priority)`는 DB의 실행 가능한 pending Work 중 더 높은 priority가 존재하는지만 확인한다.

학교/대회 같은 의미를 scheduler enum에 추가하지 않는다.

## 테스트

- 두 concurrent claim 중 하나만 성공
- P0가 P4보다 먼저 claim
- not_before 미래 Work skip
- heartbeat owner mismatch 실패
- lease expiration 후 requeue
- complete 후 다시 claim 불가
- expired recovery Event 존재
- DB row + Event atomicity

## 하지 말 것

- Redis
- Celery
- provider별 queue
- BackgroundTaskClass 종류 확장
- automatic retry policy reasoning
- cron/trigger engine

## 완료조건

1. process-local heap 없이 PostgreSQL에서 claim 가능
2. crash 뒤 lease expiration으로 Work 회수 가능
3. double claim 방지
4. priority ordering 유지
5. canonical Work transition과 Event atomic
