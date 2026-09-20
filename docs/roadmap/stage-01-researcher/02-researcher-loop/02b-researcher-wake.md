# 02B — Researcher Wake and Typed Decision

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02A + 04A model wiring
- 완료 후 열림: 02C
- contracts: ../../plan-verification-contract.md

## 목적

trigger opportunity와 ObservationSnapshot을 받아 NOOP 또는 검증 가능한 typed control-plane decision을 생성한다.

## Dependencies

ResearcherService는 provider-specific LiteLLMClient를 직접 받지 않는다.

- ObservationBuilder
- AgentExecutionPort 또는 PydanticAI Researcher agent
- logical ModelRoute
- BudgetPolicy
- store/event dependencies

## Wake order

1. short concurrent-wake lock
2. researcher.woke Event
3. ObservationSnapshot 생성
4. preflight: no new observation / disabled / budget unavailable
5. model invocation
6. discriminated typed decision validation
7. evidence/source ownership validation
8. decision Event 저장
9. 02C materialization
10. 성공적으로 durable commit된 뒤 cursor CAS advance
11. lock release

## Typed decision union

공통 fields:

- decision_id
- summary
- reason
- evidence_refs[]
- decision_schema_version
- prompt_version/ref

action별 payload를 하나의 arbitrary object로 두지 않는다.

### NOOP

payload 없음.

### CREATE_GOAL

- title
- objective
- priority_hint optional
- project_id optional
- source/evidence refs

### CREATE_WORK

- target_goal_id
- title
- objective/payload ref
- priority_hint optional
- parent_work_id optional

### REVISE_WORK

- target_work_id
- revision_intent
- replacement/patch typed fields
- reason/evidence 필수

### ASK_USER

- target_work_id
- question text/content ref
- answer schema/options optional
- expires_at optional

### PROPOSE_IMPROVEMENT

- target_type/id
- candidate intent
- expected improvement
- evidence refs

Pydantic discriminated union 또는 동등한 schema로 action과 payload mismatch를 reject한다.

## Validation

- unknown evidence ref → reject
- 다른 user/project scope ref → authority check 없이 사용 금지
- arbitrary status/SQL/path/credential을 model payload로 직접 수용 금지
- malformed output을 heuristically 보정해 mutation 금지
- parse retry는 00B에서 확정된 model retry owner/policy 안에서만 수행

## Requirements

| ID | 요구 | 검증 |
|---|---|---|
| 02B-01 | observation 없음 → model call 0 + NOOP | unit/integration |
| 02B-02 | 각 action union parse/validate | schema tests |
| 02B-03 | action/payload mismatch reject | negative tests |
| 02B-04 | unknown/cross-owner evidence reject | negative tests |
| 02B-05 | malformed output → mutation 없음 | integration |
| 02B-06 | prompt/schema/model refs provenance 기록 | store assertion |

## 완료조건

model output이 자유 payload가 아니라 action-specific typed decision으로 닫히며 invalid decision이 downstream mutation에 도달하지 않아야 한다.
