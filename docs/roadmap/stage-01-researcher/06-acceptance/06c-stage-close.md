# 06C — Stage 1 Close Checklist

## Status

- 상태: **선행작업 대기**
- 선행조건: 06B 전체 통과
- 지금 시작 가능: **아니오**

## Required evidence

### L0

- unit/contract/eval/architecture tests

### L1

- real PostgreSQL
- selected durable backend
- model/tool gateway
- concurrency/dedup/budget
- report/storage

### L2

- process kill/restart
- V1→V2 history
- NEED_USER
- external side-effect ambiguity

### L3

- AWS reboot
- backup/restore
- actual deployment/rollback
- laptop approval attack fixtures

필수 lane이 skip/not-run이면 close 불가.

## Operations

- exact deployed versions recorded
- health/readiness
- secret/data inventory
- retention/backup
- deployment rollback
- laptop offline behavior
- daily report time policy

## Documentation

같은 변경에서:

- 하위 packet status
- 01~05 parent
- Stage 1 index
- docs/roadmap.md
- architecture/ADR
- Current Position
- downstream Stage 2 plan invalidation/review marker

## Close prohibition

하나라도 사실이면 완료 처리하지 않는다.

- restart에서 researcher state 손실
- autonomous outcome이 mock/activity에만 존재
- code promotion이 실제 deployment/versioning을 거치지 않음
- protected change AWS 우회 가능
- report가 source-backed 복원을 못함
- user priority가 resource dispatch에 반영 안 됨
- explicit choice가 inferred preference로 바뀜
- required L2/L3 test가 not-run
- data/secret/artifact contract 미검증
