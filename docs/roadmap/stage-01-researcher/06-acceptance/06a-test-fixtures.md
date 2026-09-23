# 06A — Stage 1 Acceptance Fixtures

## Status

- 상태: **선행작업 대기**
- 선행조건: 01~05 구현 완료
- 지금 시작 가능: **아니오**

## 목적

Stage 1 acceptance를 reproducible fixture + environment profile로 만든다.

## Fixture groups

### Semantic/domain

- unknown-problem events without hidden cause label
- autonomous opportunity
- user feedback conflict
- low/high commitment
- unknown cost
- late report Event

### Failure

- crash barriers
- duplicate start/signal/materialization
- external mutation invocation/applied counters
- gateway outage
- worker timeout
- V1 persisted history

### Security/data

- secret canaries
- protected candidate
- unknown protection impact
- approval replay/expiry/hash mismatch
- artifact hash substitution
- user A/B access

## Environment profiles

- unit
- local-live: PostgreSQL + selected substrate
- crash-live: child processes
- deployed: AWS runtime
- authority: laptop + AWS attacker fixture

test runner output은 어떤 profile이 실행/skip/not-run 되었는지 명시한다.
필수 profile not-run은 Stage success가 아니다.

## Wrong implementation fixtures

최소 대표 실패 구현을 검증:

- duplicate effect
- Work-level single ExecutionRef
- caller-supplied correlation replay
- ordinary-by-unknown protection
- mutable candidate approval
- missing metric=0
