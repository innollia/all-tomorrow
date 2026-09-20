# 01A — Semantic Schema Migration

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료
- 완료 후 열림: 01B
- contracts: ../../domain-contracts.md, ../../plan-verification-contract.md

## 목적

기존 thin tasks를 Goal/Work/Run semantic state로 확장하되 durable backend queue/checkpoint schema를 복제하지 않는다.

## Migration policy

- 0001/0002 등 기존 migration은 과거 사실로 유지
- 새 forward migration으로만 변경
- 기존 row identity와 provenance 보존
- migration 전/후 row-count 및 key mapping fixture를 둠

## goals

최소 semantic fields:

- goal_id
- user_id
- project_id
- title
- objective
- semantic_status
- priority
- origin
- metadata
- revision
- created_at / updated_at

## work_items

기존 tasks를 rename/변환하며 row identity를 보존한다.

최소:

- work_id
- goal_id
- user_id
- project_id
- title
- semantic_status
- priority
- origin
- trace_id
- payload/reference
- wait_reason
- parent_work_id
- lineage refs
- revision
- timestamps

**execution_backend / execution_id / execution_version을 Work에 두지 않는다.**
Work는 여러 Run을 가질 수 있으므로 external execution linkage는 Run이 소유한다.

## runs

Run은 Work의 한 logical execution attempt다.

최소:

- run_id PK
- work_id FK
- semantic_status
- attempt_origin / reason
- execution_backend nullable
- execution_id nullable
- execution_version nullable
- trace_id
- started_at / terminal_at
- revision
- created_at / updated_at

제약:

- Work 1:N Run
- 하나의 Run에는 최대 하나의 active logical ExecutionRef
- runs.trace_id UNIQUE 금지
- terminal Run을 새 attempt로 재사용 금지
- backend internal status/schema column 복제 금지

## outcomes

CompletionEvidence/OutcomeRecord persistence:

- outcome_id
- target_type / target_id
- status
- criterion_ref/version
- evidence_refs / artifact_refs
- observed_values
- evaluator_ref/version
- created_at

Work/Goal SUCCEEDED transition은 outcome/evidence linkage를 가져야 한다.

## delivery_records

cross-store intent/reconciliation metadata:

- delivery_id
- kind
- subject refs
- destination ref
- idempotency key + namespace/version
- status
- attempts/error/next_attempt
- timestamps

durable execution queue 자체를 복제하는 table이 아니다.

## questions

기존 user_questions가 있으면 canonical contract로 확장:

- question_id
- work_id/run_id
- status: PENDING / ANSWERED / SUPERSEDED / CANCELLED / EXPIRED
- answer_ref
- signal correlation
- revision/timestamps

## project/source refs

기존 project schema가 있으면 재사용/확장한다.

- canonical Project identity
- SourceRef owner/type/id/version/hash/freshness/access metadata
- host-local workspace path를 canonical source record에 저장하지 않음

새 중복 project registry를 만들지 않는다.

## events

- event provenance가 Run 삭제/정리와 함께 cascade 소실되지 않음
- Goal/Work/Run/source/external refs 연결 가능
- payload에는 raw provider object/secret를 저장하지 않음

## 삭제/금지 대상

All Tomorrow queue authority 목적으로 다음을 추가하지 않는다.

- claimed_by
- lease_expires_at
- attempt_count as backend retry bookkeeping
- custom claim/lease recovery index

priority는 semantic domain field이며 adapter가 backend priority로 변환한다.

## Requirement / verification

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 01A-01 | 기존 task/goal data 보존 | pre/post fixture + live migration row mapping | L1 |
| 01A-02 | Work 1:N Run | DB constraint/integration | L1 |
| 01A-03 | ExecutionRef fields는 Run에만 존재 | schema fitness test | L0 |
| 01A-04 | queue/lease mechanics 없음 | schema grep/architecture test | L0 |
| 01A-05 | event provenance 비-cascade 보존 | deletion/retention integration | L1 |
| 01A-06 | migration chain이 빈 DB와 기존 fixture DB 모두 통과 | migration integration | L1 |
| 01A-07 | Work/Goal success가 Outcome linkage를 가질 수 있음 | schema/integration | L1 |
| 01A-08 | Delivery/Question canonical lifecycle schema 존재 | schema/integration | L1 |
| 01A-09 | Project/SourceRef가 기존 project system과 중복 정본을 만들지 않음 | architecture/schema review | L0 |

## 완료조건

위 요구가 모두 통과하고, 01B가 Goal/Work/Run semantic store를 구현할 수 있는 schema가 확정되어야 한다.
