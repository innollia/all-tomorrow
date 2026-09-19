# 01D — Work ↔ Run Linkage

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01B 완료
- 01C와 병렬 가능: **예**
- 완료 후 열림: 01E

## 목적

현재 `PipelineRuntime.start(spec, context)`가 독립 Run만 만드는 구조를 유지하면서, durable Work가 여러 Run 시도를 소유할 수 있게 연결한다.

Pipeline을 Goal manager로 키우지 않는다.

## 수정 파일

- 수정: `src/all_tomorrow/storage/run_store.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 수정: `src/all_tomorrow/pipeline/runtime.py`
- 수정: `tests/test_runtime.py`
- 수정: `tests/test_postgres_store.py`

## RunRecord

필드 추가:

- `work_id: str | None = None`

serialization:

- `run_record_to_dict()`에 work_id
- `run_record_from_dict()`에서 work_id 복원

기존 standalone pipeline tests를 깨지 않기 위해 nullable 유지.

## PipelineRuntime.start

signature:

`start(spec, context, *, work_id: str | None = None)`

- 기존 caller는 수정 없이 동작
- Work executor가 부를 때만 work_id 전달
- 새 RunRecord.work_id에 기록
- Work가 있으면 Run의 trace_id는 Work.trace_id와 같아야 함
- trace mismatch면 실행 전에 ContractError

## PostgresStore.create_run

INSERT에 `work_id` 추가.

Work가 존재할 때:

- FK로 존재 검증
- Run 하나가 추가될 때 Work를 덮어쓰지 않음
- 동일 work_id 아래 여러 Run 허용

## RunResult

`work_id: str | None` 추가.

UI/상위 orchestration이 결과를 Work로 되돌려 연결할 수 있게 한다.

## Work completion ownership

PipelineRuntime 자체는 Run 결과만 결정한다.

다음은 하지 않는다:

- Run SUCCEEDED → Work SUCCEEDED 자동 결정
- Run FAILED → Work FAILED 자동 결정

이 해석은 Researcher/Orchestrator가 담당한다.

Stage 1.2에서는 한 Run 실패 후 같은 Work에서 replan/new Run을 만들 수 있어야 한다.

## Production Run/Event transaction 보강

현재 runtime은 `store.update_run()` 뒤 별도 `event_sink.append()`를 호출한다.

PostgreSQL production path에 한해 다음 helper를 추가한다:

- `PostgresStore.create_run_with_event(run, event)`
- `PostgresStore.update_run_with_event(run, expected_revision, event)`

둘 다 한 transaction.

`PipelineRuntime` 내부에 작은 persistence helper를 두고:

- store가 위 atomic method를 지원하고
- event sink가 같은 PostgresStore의 `PostgresEventSink`인 경우

run.started / run.succeeded / run.failed / run.cancelled 같은 **state transition event**는 atomic method 사용.

단순 step.started 같은 observation Event는 기존 sink 사용.

NEED_USER의 question + run state는 기존 `resume_run` 수준과 같은 atomicity를 갖도록 별도 store method로 묶는다:

- `suspend_run_for_user(run, expected_revision, question_record, event)`

한 transaction에서 question INSERT + run NEED_USER update + Event append.

InMemory path는 기존 semantics를 유지하되 테스트가 깨지지 않게 한다.

## 테스트

- standalone start(work_id=None) 기존 테스트 유지
- work_id 전달 시 RunRecord/RunResult/Postgres row에 보존
- 한 work_id 아래 두 Run 생성 가능
- 동일 trace 아래 여러 Run 가능
- Work trace와 context trace mismatch 실패
- run.succeeded transition에서 UPDATE와 Event INSERT가 같은 transaction
- NEED_USER suspend가 question/run/Event 한 transaction
- 실패한 transaction에 orphan Event 없음

## 하지 말 것

- PipelineRuntime이 Goal status 결정
- Pipeline node 안에서 Work row 직접 수정
- Pipeline마다 Work lifecycle logic 복제
- 모든 step Event까지 별도 복잡한 transaction framework로 감싸기

## 완료조건

1. Work → Run 1:N 연결
2. trace 1:N Run 가능
3. PipelineRuntime의 기존 standalone 사용법 유지
4. 주요 Run state transition과 Event가 production PostgreSQL에서 atomic
5. NEED_USER suspend가 restart-safe
