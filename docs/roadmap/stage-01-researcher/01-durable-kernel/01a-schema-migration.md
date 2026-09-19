# 01A — Schema Migration

## Status

- 상태: **시작안했음**
- 지금 시작 가능: **예**
- 선행조건: 없음
- 완료 후 열림: 01B Domain & Store, 01C Durable Queue

## 목적

현재 얇은 `tasks`, 단일-run을 암시하는 `runs.trace_id UNIQUE`, run 삭제에 따라 사라지는 Event FK를 Stage 1의 Goal/Work/Run 모델로 바로잡는다.

## 수정 파일

- 새 파일: `migrations/0003_durable_work.sql`
- 수정: `tests/test_migration.py`

`0001_core.sql`을 과거 migration으로 유지한다. 새 구조를 만들기 위해 0001을 다시 쓰지 않는다.

## 현재 코드에서 확인된 문제

- `tasks`는 task_id/title/status/priority만 존재
- `runs.task_id`는 있지만 현재 `PostgresStore.create_run()`이 task_id를 기록하지 않음
- `runs.trace_id`가 UNIQUE라 하나의 trace 아래 여러 Run을 둘 수 없음
- `events.run_id ... ON DELETE CASCADE`라 Run 삭제 시 audit provenance도 삭제됨

## 0003 SQL 순서

### 1. Goal table 추가

`goals`:

- `goal_id text PRIMARY KEY`
- `user_id text NOT NULL`
- `project_id text NULL REFERENCES projects(project_id)`
- `title text NOT NULL`
- `objective text NOT NULL`
- `status text NOT NULL CHECK status IN ('ACTIVE','PAUSED','COMPLETED','CANCELLED')`
- `priority integer NOT NULL DEFAULT 2 CHECK priority BETWEEN 0 AND 6`
- `origin text NOT NULL`
- `metadata jsonb NOT NULL DEFAULT '{}'`
- `revision bigint NOT NULL DEFAULT 0`
- `created_at/updated_at timestamptz NOT NULL DEFAULT now()`

index:

- `goals_user_status_idx(user_id, status, updated_at DESC)`
- `goals_project_status_idx(project_id, status, updated_at DESC)` WHERE project_id IS NOT NULL

### 2. tasks를 work_items로 승격

기존 data/history를 버리지 말고 rename:

- `ALTER TABLE tasks RENAME TO work_items`
- `task_id → work_id`

추가 column:

- `goal_id text NULL REFERENCES goals(goal_id)`
- `user_id text NULL` — legacy row 때문에 migration에서는 nullable, 새 write contract에서는 필수
- `trace_id text NULL` — legacy row 때문에 nullable, 새 Work 생성에서는 필수
- `origin text NOT NULL DEFAULT 'user'`
- `payload jsonb NOT NULL DEFAULT '{}'`
- `wait_reason text NULL`
- `not_before timestamptz NULL`
- `parent_work_id text NULL REFERENCES work_items(work_id)`
- `claimed_by text NULL`
- `lease_expires_at timestamptz NULL`
- `attempt_count integer NOT NULL DEFAULT 0 CHECK attempt_count >= 0`
- `revision bigint NOT NULL DEFAULT 0`

새 Work status 허용값은:

`PENDING / RUNNING / WAITING / SUCCEEDED / FAILED / CANCELLED`

기존 row가 있을 수 있으므로 CHECK를 추가하기 전에 허용값 밖 status가 존재하면 migration을 조용히 변환하지 말고 명시적으로 실패시키는 guard를 넣는다.

index:

- claim용 partial index: `(priority, not_before, created_at, work_id)` WHERE status='PENDING'
- `work_items_goal_idx(goal_id, created_at)`
- `work_items_trace_idx(trace_id)` WHERE trace_id IS NOT NULL
- lease recovery용 `work_items_lease_idx(lease_expires_at)` WHERE status='RUNNING'

### 3. runs를 Work에 연결

- `runs.task_id → runs.work_id`
- 기존 FK는 rename된 `work_items(work_id)`를 가리키도록 유지/재생성
- `UNIQUE(trace_id)` 제거
- 비고유 `runs_trace_idx(trace_id, created_at)` 추가
- `runs_work_idx(work_id, created_at)` 추가

한 Work가 여러 Run을 가질 수 있고, 하나의 trace가 여러 Work/Run을 묶을 수 있어야 한다.

### 4. Event audit retention 수정

`events.run_id` FK의 `ON DELETE CASCADE` 제거.

목표:

- Run row를 정리해도 Event provenance가 자동 삭제되지 않음
- `ON DELETE SET NULL` 사용
- `events.trace_id`는 그대로 유지되어 lineage를 잃지 않음

`run_steps`와 `user_questions`의 lifecycle FK는 이번 packet에서 건드리지 않는다.

## 테스트 변경

`tests/test_migration.py`:

- 0001의 과거 구조 검사와 0003의 upgrade 검사 분리
- 더 이상 최종 요구사항으로 `tasks`와 `UNIQUE(trace_id)`를 주장하지 않음
- 0003에 다음 문자열/구조가 존재하는지 검증:
  - goals
  - work_items rename
  - work_id
  - goal_id
  - lease_expires_at
  - parent_work_id
  - trace UNIQUE 제거
  - non-unique trace index
  - events run FK audit retention

가능하면 live PostgreSQL migration test는 01E에서 수행하고, 여기서는 migration 문서 구조만 빠르게 검증한다.

## 하지 말 것

- 0001_core.sql을 새 최종 schema처럼 다시 작성
- Artifact/Trigger/Knowledge table까지 같이 추가
- Redis 추가
- multi-host executor schema 추가
- researcher prompt/model schema 추가

## 완료조건

1. 빈 DB에서 0001 → 0002 → 0003 순차 적용 가능
2. 기존 task row가 rename으로 보존
3. 하나의 trace에 여러 Run 생성 가능한 schema
4. Event가 Run 삭제 cascade에 묶이지 않음
5. migration unit test 통과
