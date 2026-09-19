# 02A — Observation Snapshot

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01 Durable Kernel 완료
- 완료 후 열림: 02B Researcher Wake

## 목적

Researcher가 매번 DB 전체를 덤프받지 않고, 현재 상황을 판단하기 위한 bounded observation snapshot을 만든다.

## 수정 파일

- 새 파일: `src/all_tomorrow/researcher.py`
- 새 파일: `src/all_tomorrow/observation.py`
- 수정: `src/all_tomorrow/storage/work_store.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 새 테스트: `tests/test_observation.py`

## ObservationSnapshot

dataclass 최소 필드:

- snapshot_id
- created_at
- trigger_origin
- user_id
- project_id optional
- active_goal_refs
- open_work_refs
- recent_run_refs
- recent_event_refs
- pending_question_refs
- recent_evaluation_refs
- recent_system_change_refs
- budget_summary
- resource_summary
- cursor/watermark

raw prompt/output 전체를 snapshot에 복제하지 않는다.

## 조회 범위

기본 조회는 bounded:

- active Goal
- PENDING/RUNNING/WAITING Work
- 최근 N개 terminal Work/Run
- 마지막 watermark 이후 Event
- pending questions
- 최근 evaluation/proposal refs

N과 lookback은 config로 두되 무한 history를 prompt에 넣지 않는다.

## Watermark

Researcher consumer별 watermark를 저장한다.

새 migration:

- `migrations/0004_researcher.sql`

table:

`observer_cursors`

- observer_id
- user_id
- last_event_at
- last_event_id
- updated_at
- PRIMARY KEY(observer_id, user_id)

Event time 동률을 고려해 occurred_at + event_id 두 값을 cursor로 사용.

## Store API

- `build_observation_snapshot(...)`
- `get_observer_cursor(...)`
- `advance_observer_cursor(...)`

cursor advance는 researcher decision이 durable하게 기록된 뒤에만 수행한다.

## 자기관찰

다음 Event도 일반 Event처럼 포함 가능:

- researcher.woke
- researcher.noop
- researcher.decision
- goal.autonomous_created
- improvement.proposed
- evaluation.completed
- promotion.applied
- rollback.applied

별도 meta-meta store를 만들지 않는다.

## 하지 말 것

- 모든 Event를 매 wake마다 읽기
- raw user prompt/secret를 snapshot metadata로 복제
- vector DB 추가
- 문제 유형 classifier 추가

## 테스트

- watermark 이후 Event만 조회
- 같은 timestamp Event 누락 없음
- active/open state 포함
- terminal history bounded
- researcher 자신의 이전 Event도 다음 snapshot에 포함
- secret/raw payload 유출 없음

## 완료조건

Researcher가 현재와 최근 변화만 bounded snapshot으로 읽고, 다음 wake에서 자기 자신의 이전 판단도 다시 볼 수 있음.
