# 01B — Goal/Work Domain and Store

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A Schema Migration 완료
- 완료 후 열림: 01D Run Linkage

## 목적

Goal/Work를 pipeline Run과 분리된 durable orchestration state로 코드에 도입한다.

## 수정 파일

- 새 파일: `src/all_tomorrow/work.py`
- 새 파일: `src/all_tomorrow/storage/work_store.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 수정: `src/all_tomorrow/storage/__init__.py`
- 수정: `src/all_tomorrow/__init__.py`
- 새 테스트: `tests/test_work_store.py`
- 보강: `tests/test_postgres_store.py`

## work.py

### Enum

`GoalStatus`:

- ACTIVE
- PAUSED
- COMPLETED
- CANCELLED

`WorkStatus`:

- PENDING
- RUNNING
- WAITING
- SUCCEEDED
- FAILED
- CANCELLED

### GoalRecord

필드:

- goal_id
- user_id
- title
- objective
- status
- priority
- origin
- project_id
- metadata
- revision
- created_at
- updated_at

factory는 `new_id("goal")` 사용 가능.

### WorkRecord

필드:

- work_id
- goal_id
- user_id
- title
- status
- priority
- origin
- trace_id
- project_id
- payload
- wait_reason
- not_before
- parent_work_id
- claimed_by
- lease_expires_at
- attempt_count
- revision
- created_at
- updated_at

새 Work는 반드시 `trace_id`를 가진다. parent Work에서 파생된 경우 기본적으로 parent의 trace_id를 이어받고, 독립 Goal root Work는 새 trace를 만든다.

## work_store.py

`WorkStateStore` Protocol만 정의한다.

필수 method:

- `create_goal(goal)`
- `get_goal(goal_id)`
- `update_goal(goal, expected_revision)`
- `create_work(work)`
- `get_work(work_id)`
- `list_goal_work(goal_id)`

queue claim/lease method는 01C에서 추가한다.

여기서 거대한 Repository abstraction을 만들지 않는다.

## PostgresStore 구현

위 method를 `PostgresStore`에 구현한다.

규칙:

- JSON field는 기존 `Jsonb` pattern 재사용
- optimistic concurrency는 현재 Run의 revision pattern 재사용
- unknown id와 revision conflict를 구분
- DB row → dataclass 변환 helper를 private function으로 분리
- status string은 Enum으로 즉시 검증
- 새 Work write에서는 migration 호환용 nullable column이라도 user_id/trace_id를 필수로 요구

## Work transition + Event

새 private helper:

- `_append_event_conn(connection, event)`

기존 `PostgresEventSink.append()`의 INSERT SQL을 이 helper로 모은다.

Work lifecycle 변경용 public method:

- `transition_work(work_id, expected_revision, *, status, event, wait_reason=None, clear_claim=False)`

이 method 하나의 PostgreSQL transaction 안에서:

1. revision/status 검증
2. Work row update
3. Event append
4. 새 WorkRecord 반환

즉 Work의 canonical projection과 그 transition Event가 따로 commit되지 않게 한다.

일반 Event append는 기존 `PostgresEventSink`를 유지하되 SQL duplication만 제거한다.

## Event metadata

Work transition event에는 raw prompt/payload를 넣지 않는다.

최소 metadata:

- work_id
- goal_id
- old_status
- new_status
- revision
- reason code가 있으면 짧은 reason

Event의 trace_id는 Work의 trace_id 사용.

## 테스트

### tests/test_work_store.py

pure domain:

- invalid status construction failure
- child Work가 parent trace를 이어받는 factory
- independent Work가 새 trace를 가짐
- priority bounds

### tests/test_postgres_store.py

mock transaction:

- create/get goal
- create/get/list work
- optimistic revision conflict
- `transition_work`가 UPDATE와 Event INSERT를 같은 transaction에서 수행
- transition 실패 시 Event INSERT 없음
- payload가 Event metadata로 새지 않음

## 하지 말 것

- Planner class 추가
- Researcher class 추가
- Work 종류 enum을 provider/project 이름으로 확장
- Goal당 하나의 Run이라고 가정
- Event만 replay해 current state를 복원하는 full event sourcing

## 완료조건

1. Goal/Work를 Run 없이 저장/조회 가능
2. Work 하나에 여러 후속 Run을 붙일 준비가 됨
3. Work state transition과 Event append가 PostgreSQL 한 transaction
4. revision conflict test 통과
5. raw task payload가 transition Event에 유출되지 않음
