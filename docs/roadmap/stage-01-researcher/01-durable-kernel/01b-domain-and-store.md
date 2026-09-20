# 01B — Goal/Work/Run Domain and Store

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A
- contracts: ../../domain-contracts.md, ../../plan-verification-contract.md

## 목적

Goal/Work/Run을 selected workflow engine과 독립된 All Tomorrow domain으로 구현한다.

## Domain records

- GoalRecord: 장기 objective와 semantic status
- WorkRecord: Goal을 진전시키는 semantic unit
- RunRecord: Work의 logical execution attempt
- ExecutionRef: Run에 연결되는 external durable execution ref

WorkRecord에 단일 ExecutionRef를 두지 않는다.

## Store responsibilities

### GoalWorkStore

- create/get/update/list Goal
- create/get/update/list Work
- semantic transition
- lineage/source refs
- transition + provenance Event atomicity

### RunStore

- create STARTING Run
- get/list Run by Work
- attach_execution_ref(run_id, expected_revision, ref)
- transition Run
- find STARTING/no-ref reconciliation candidates
- record explicit unknown/repair evidence

RunStore가 backend system table을 직접 조회/수정하지 않는다.

## Concurrency

- optimistic revision 또는 DB row lock으로 lost update 방지
- semantic transition은 expected current state/revision을 검사
- ExecutionRef attach는 compare-and-set
- 다른 ref가 이미 붙은 경우 overwrite하지 않고 invariant violation
- duplicate create에는 idempotency key/unique constraint가 있는 operation만 재사용

## State machine

../../domain-contracts.md의 Work/Run state semantics를 사용한다.

특히:

- Run 실패가 Work를 자동 FAILED로 만들지 않음
- terminal Work/Run을 조용히 되살리지 않음
- cancellation requested와 completed를 구분
- WAITING은 backend status 복사가 아님

## Priority

P0~P6은 semantic policy다.
backend numeric priority/range를 domain enum에 넣지 않는다.

## Requirement / verification

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 01B-01 | backend import 없이 Goal/Work/Run CRUD | domain/store test | L0/L1 |
| 01B-02 | Work 1:N Run | integration | L1 |
| 01B-03 | transition + Event atomic | forced transaction failure | L1 |
| 01B-04 | concurrent revision 충돌이 lost update를 만들지 않음 | concurrent transaction test | L1 |
| 01B-05 | ExecutionRef conflicting attach fail closed | CAS race test | L1 |
| 01B-06 | backend internal type/status가 domain에 없음 | architecture fitness | L0 |

## 완료조건

Goal/Work/Run semantic state와 provenance를 실제 PostgreSQL에서 안전하게 유지하고, external execution 없이도 domain 의미를 완전히 설명할 수 있어야 한다.
