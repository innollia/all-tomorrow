# 01D — Run / Compatibility Linkage

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01B + 01C
- contracts: ../../domain-contracts.md, ../../plan-verification-contract.md

## 목적

기존 PipelineRuntime 자산과 새 Run/durable/agent substrate를 연결하되 identity와 recovery authority를 중복하지 않는다.

## Canonical roles

- Work: semantic unit
- Run: Work의 logical execution attempt + idempotency identity
- ExecutionRef: Run의 external durable execution
- AgentInvocation: PydanticAI interaction provenance
- PipelineRuntime execution: deterministic/versioned recipe의 내부 실행 기록

"legacy run"이라는 모호한 표현 대신 기존 PipelineRuntime ID는 pipeline_execution_id처럼 별도 provenance ref로 취급한다.

## PipelineRuntime disposition

00E ADR에서 maintain / compatibility-only / retire 중 하나를 확정한다.

maintain인 경우:

- DurableExecutionPort 안의 bounded executor/component로 사용 가능
- researcher agentic decision path를 강제하지 않음
- process crash recovery/retry ownership을 durable backend와 중복하지 않음
- 내부 node retry는 selected retry policy 안의 bounded local operation일 뿐 durable recovery가 아님

## Provenance

최소 연결:

- goal_id
- work_id
- run_id
- ExecutionRef backend/id/version
- pipeline_execution_id optional
- PydanticAI/OTel span ref
- worker/tool request id
- ArtifactRef/result refs

## NEED_USER

canonical Question contract를 사용한다.

- Question projection은 UI/authorization 의미
- backend wait/signal은 durable mechanism
- question_id ↔ signal_id 연결
- answer persistence 후 signal
- duplicate answer/signal idempotent
- restart 중 같은 질문 record 재생성 금지
- terminal/cancelled Work에 late answer가 와도 새 실행을 암묵 생성하지 않음

기존 user_questions table이 이 contract를 만족하면 migration으로 확장하고, 만족하지 못하면 새 schema를 만든다. 선택 자체는 01D 구현 전에 확정하며 02C로 미루지 않는다.

## Requirement / verification

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 01D-01 | Work→여러 Run→각 ExecutionRef lineage | integration | L1 |
| 01D-02 | PipelineRuntime regression 보존 또는 ADR대로 retire | regression/ADR | L0/L1 |
| 01D-03 | researcher가 PipelineRuntime type에 강제 종속되지 않음 | architecture test | L0 |
| 01D-04 | NEED_USER restart + duplicate answer/signal 안전 | process restart integration | L2 |
| 01D-05 | 전체 provenance graph 연결 가능 | trace/store assertion | L1 |

## 완료조건

기존 실행 자산을 보존할 범위가 명시되고, Run/Question/provenance identity가 새 durable substrate와 충돌 없이 연결되어야 한다.
