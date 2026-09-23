# 02A — Observation Snapshot

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01 Durable Kernel 완료
- 완료 후 열림: 02B
- contracts: ../../domain-contracts.md, ../../plan-verification-contract.md

## 목적

Researcher가 DB 전체를 덤프받지 않고 bounded, reproducible observation range를 읽게 한다.

## ObservationSnapshot

최소:

- snapshot_id
- created_at
- trigger_origin/ref
- user_id
- project_id optional
- active_goal_refs
- open_work_refs
- recent_run_refs
- event_range: lower_cursor exclusive / upper_cursor inclusive
- pending_question_refs
- recent_evaluation/proposal refs
- recent_system_change refs
- budget_summary
- resource_summary
- projection_version

raw prompt/output/secret를 snapshot metadata에 복제하지 않는다.

## Bounded query

- active Goal
- PENDING/RUNNING/WAITING Work
- 최근 N terminal Work/Run
- cursor 이후 Event 중 snapshot 생성 시점의 upper bound까지
- pending Question
- recent evaluation/proposal refs

N/lookback은 config version으로 기록한다. 무한 history를 prompt에 넣지 않는다.

## Cursor

observer_cursors:

- observer_id
- user_id
- last_event_at
- last_event_id
- revision
- updated_at
- PK(observer_id,user_id)

occurred_at + event_id tuple로 ordering한다.

snapshot 생성 시 current cursor와 max visible Event를 읽어 immutable range를 만든다.
cursor는 decision/materialization이 durable하게 끝난 뒤 expected revision/CAS로 advance한다.

## Concurrent wake

동일 observer_id/user_id의 model call 중복을 줄이기 위해 PostgreSQL advisory lock 또는 동등한 DB-scoped short lock을 사용한다.

- lock 획득 실패 시 같은 cursor range를 별도 처리하지 않고 이미 진행 중 상태로 종료/재시도
- process crash 시 DB session 종료로 lock 자동 해제
- 장기 lease/heartbeat subsystem을 새로 만들지 않음
- cursor CAS는 최종 duplicate protection으로 유지

## Self observation

researcher.woke/noop/decision, autonomous Goal/Work, proposal/evaluation/promotion/rollback Event도 일반 Event처럼 다음 range에 포함될 수 있다.

## Requirements

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 02A-01 | same timestamp Event 누락 없음 | cursor ordering test | L1 |
| 02A-02 | terminal history bounded | property test | L0 |
| 02A-03 | snapshot range 재현 가능 | same cursor fixture | L1 |
| 02A-04 | concurrent wake가 same range model call을 중복 시작하지 않음 | concurrent DB test | L1 |
| 02A-05 | crash 후 lock 해제 + cursor 미진행 | child process test | L2 |
| 02A-06 | raw secret/content가 snapshot metadata에 복제되지 않음 | canary test | L1 |

## 완료조건

현재와 최근 변화만 bounded range로 읽으며 concurrent/crash 상황에서도 range 누락·중복 mutation의 원인이 되지 않아야 한다.
