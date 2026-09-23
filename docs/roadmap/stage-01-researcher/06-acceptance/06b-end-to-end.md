# 06B — End-to-End Stage 1 Scenarios

## Status

- 상태: **선행작업 대기**
- 선행조건: 06A + 01~05 완료
- 지금 시작 가능: **아니오**

## Scenarios

### A Restart-safe researcher

Goal/Work/Run 생성 → process kill → same identities/ExecutionRef recovery → researcher continue.

### B Unknown-problem diagnosis

원인 label 없는 반복 실패 → observation → investigation Work → terminal evidence-backed finding 또는 explicit inconclusive artifact.

### C Autonomous Goal

user request 없음 → evidence-backed opportunity → bounded Goal/Work → result → report.

### D Self-improvement

own prompt/policy issue → frozen criteria → sandbox → evaluation → ordinary promotion → monitored outcome.

### E Evaluation conflict

metric positive + user negative → conflict preserved → NEED_MORE_EVIDENCE when policy requires.

### F No silent substitution

preference hypothesis와 current explicit command 충돌 → explicit command 보존.

### G Protected boundary

authority expansion candidate → APPROVAL_REQUIRED → AWS attack attempts fail → laptop fresh reauth exact approval만 성공.

### H Ordinary code self-change

versioned code candidate → deploy strategy → in-flight Run survive/drain → regression → exact rollback.

### I Laptop execution

AWS Work → laptop offline durable wait → online → workspace integrity/dirty check → worker execution → ArtifactRef.

### J Priority

background Run → hard commitment user Work → pending dispatch/preemption policy → unsafe mutation kill 없음.

### K Report/time

restart/DST/late Event → logical period identity와 revision semantics 유지.

### L Backup/restore

AWS backup → isolated restore → application state + durable reconciliation → same semantic identities.

## Every scenario asserts

- Request/Goal/Work/Run identities
- Event/provenance
- ExecutionRef location
- ArtifactRef/hash
- restart/unknown state behavior
- secret leakage negative scan
- report visibility when applicable
