# 03A — Improvement and Evaluation Persistence

## Status

- 상태: **선행작업 대기**
- 선행조건: 02 Researcher Loop 완료
- 지금 시작 가능: **아니오**
- 완료 후 열림: 03B

## 목적

ImprovementProposal/Evaluation을 immutable refs와 versioned criteria를 가진 durable lifecycle로 승격한다.

## Tables

### improvement_proposals

- proposal_id
- target_type / target_id
- baseline_ref + immutable hash/version
- candidate_ref + immutable hash/version optional until sandboxed
- reason
- status
- protection_class
- source_goal_id/work_id
- evidence_refs
- criteria_ref
- metadata
- revision
- timestamps

status:
PROPOSED / SANDBOXED / EVALUATED / ACCEPTED / REJECTED / PROMOTED / ROLLED_BACK / APPROVAL_REQUIRED / STALE

### evaluation_criteria

평가기준을 candidate 결과와 분리해 versioned/frozen snapshot으로 저장한다.

- criteria_id/version
- proposal_id
- generated_from refs
- common required metrics
- dynamic criteria
- hard invariants
- frozen_at
- content hash

candidate execution 시작 전에 freeze한다.

### evaluation_runs

- evaluation_id
- proposal_id
- criteria_ref
- baseline_ref/hash
- candidate_ref/hash
- common/dynamic/user evidence refs
- decision
- reason
- evaluator version/ref
- created_at

### user_feedback

- feedback_id
- user_id
- target_type/id
- rating/text ref optional
- source
- occurred_at
- metadata

raw conversation 전체를 복제하지 않는다.

## Immutability

proposal ACCEPT 이후 candidate hash/version이 바뀌면 기존 evaluation/approval은 무효이며 proposal은 STALE 또는 새 revision으로 재평가한다.

evaluation criteria도 candidate가 변경할 수 있는 mutable working-tree file만으로 참조하지 않는다.

## Atomicity

모든 proposal status change + Event는 같은 transaction.
illegal transition은 reject한다.

## Requirements

| ID | 요구 | 검증 |
|---|---|---|
| 03A-01 | restart 후 lifecycle/provenance 보존 | PostgreSQL integration |
| 03A-02 | criteria candidate 실행 전 freeze | ordering test |
| 03A-03 | candidate hash 변경 시 prior evaluation 무효 | stale test |
| 03A-04 | status + Event atomic | transaction failure |
| 03A-05 | observation에서 proposal/eval refs 재사용 가능 | projection test |

## 완료조건

proposal, frozen criteria, evaluation, user evidence가 immutable provenance로 연결되어 이후 candidate가 자신의 평가 기록을 바꿀 수 없어야 한다.
