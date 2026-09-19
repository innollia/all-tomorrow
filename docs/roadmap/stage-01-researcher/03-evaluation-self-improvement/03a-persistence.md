# 03A — Improvement and Evaluation Persistence

## Status

- 상태: **선행작업 대기**
- 선행조건: 02 Researcher Loop 완료
- 지금 시작 가능: **아니오**
- 완료 후 열림: 03B Mixed Evaluation

## 목적

현재 in-memory dataclass 수준의 ImprovementProposal/EvaluationScore를 durable lifecycle로 승격한다.

## 수정 파일

- 새 migration: `migrations/0005_improvement.sql`
- 수정: `src/all_tomorrow/evaluation.py`
- 새 파일: `src/all_tomorrow/storage/evaluation_store.py`
- 수정: `src/all_tomorrow/storage/postgres.py`
- 새 테스트: `tests/test_evaluation_store.py`

## Tables

### improvement_proposals

- proposal_id PK
- target_type
- target_id
- baseline_ref
- candidate_ref
- reason
- status
- protection_class
- source_goal_id optional
- source_work_id optional
- evidence_refs jsonb
- metadata jsonb
- revision
- created_at/updated_at

status:

PROPOSED / SANDBOXED / EVALUATED / ACCEPTED / REJECTED / PROMOTED / ROLLED_BACK / APPROVAL_REQUIRED

### evaluation_runs

- evaluation_id PK
- proposal_id FK
- baseline_ref
- candidate_ref
- criteria jsonb
- common_metrics jsonb
- dynamic_metrics jsonb
- user_evidence_refs jsonb
- decision
- reason
- created_at

### user_feedback

Stage 1 최소:

- feedback_id
- user_id
- target_type
- target_id
- rating/text optional
- source
- occurred_at
- metadata

raw conversation 전체 저장은 하지 않는다.

## Existing API compatibility

현재 `EvaluationScore`, `ImprovementProposal`, `EvaluationService.compare()` 테스트를 당장 깨지 않는다.

새 lifecycle은 기존 compare 위에 확장하고 나중에 단순 fixed-score compare를 내부 helper로 축소 가능.

## Store API

- create/get/update proposal
- append evaluation
- list proposal evaluations
- append/list user feedback
- list pending approval proposals

모든 status change는 Event와 같은 transaction으로 기록.

## 완료조건

proposal/evaluation/user feedback이 restart 뒤에도 보존되고 provenance로 다시 researcher observation에 들어갈 수 있음.
