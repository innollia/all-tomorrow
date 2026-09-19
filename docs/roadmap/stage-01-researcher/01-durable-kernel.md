# Stage 1.1 — Minimal Durable Kernel

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- 다음으로 여는 작업: Researcher Loop

## Goal

Researcher가 재시작과 여러 실행 시도를 견디도록 최소 중앙 상태를 만든다.

## Read with

- ../../decisions/0002-durable-work-above-pipeline.md
- 필요할 때만 ../../architecture.md의 Goal/Work, Persistence 절

## Scope

### Goal / Work / Run

- Goal: 여러 Work와 시간대를 넘어 유지되는 목적
- WorkItem: durable 실행 단위
- Run: WorkItem의 한 실행 시도
- Run 실패가 Goal 실패를 자동 의미하지 않음

현재 tasks를 폐기부터 하지 않는다. 기존 schema를 확장할 수 있는지 먼저 검토하고 필요한 persistence만 추가한다.

### State + Event

- 현재 상태 projection은 PostgreSQL row
- Event는 append-only provenance/observation
- 상태 변경과 관련 Event append의 transaction boundary 명확화
- full event sourcing은 요구하지 않음

### Minimal lifecycle

Work:
PENDING / RUNNING / WAITING / SUCCEEDED / FAILED / CANCELLED

Goal:
ACTIVE / PAUSED / COMPLETED / CANCELLED

세부 원인은 wait_reason, metadata, Event로 표현한다.

### Recovery

- process restart 후 Goal/Work/Run 조회
- durable enqueue/claim
- retry/requeue
- cancellation
- concurrent resume 방지
- NEED_USER question → restart → answer → same Work/Run resume
- provenance retention

### Trace correction

하나의 trace 아래 여러 Work/Run이 존재할 수 있어야 한다. 현재 runs.trace_id UNIQUE 같은 제약이 이 모델과 충돌하는지 migration review에서 확인한다.

## Not Here

- researcher reasoning prompt
- LiteLLM
- Web UI
- multi-host workspace
- self-improvement evaluation logic

## Done When

1. 실제 PostgreSQL clean migration 통과
2. Work 실행 중 process kill/restart 후 유실 없음
3. NEED_USER restart-resume 통과
4. 한 Goal 아래 여러 Work/Run provenance 조회 가능
5. state mutation과 Event 사이에 설명되지 않는 불일치 없음
