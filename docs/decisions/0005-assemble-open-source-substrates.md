# ADR 0005: Assemble Open-Source Substrates, Own Semantics

Status: Accepted

Date: 2026-09-19

## Context

All Tomorrow의 초기 계획은 durable queue, lease/heartbeat, workflow recovery, LLM gateway client, agent execution, evaluation과 telemetry 중 여러 부분을 직접 구현하는 방향으로 커졌다.

이 중 상당수는 이미 유지보수되는 OSS가 해결하고 있다. 직접 재구현하면 All Tomorrow 고유 문제보다 범용 인프라 복제에 시간이 쓰이고, 실패 모드도 늘어난다.

반대로 외부 프로젝트 하나를 중앙 정본으로 삼으면 vendor 내부 상태에 domain 의미가 잠겨 교체가 어려워진다.

## Decision

All Tomorrow는 assemble-first 전략을 사용한다.

### 직접 소유

- Goal/Work semantic state
- user/project/source ownership
- context assembly
- planner/metacognition
- authority/protected-change policy
- cross-system provenance

### 초기 substrate

- PydanticAI: agent/tool/MCP/typed-output/eval interface
- DBOS와 Restate: first durable backend finalists
- FastMCP: stable MCP gateway/composition candidate
- LiteLLM Proxy: model/provider gateway
- OpenTelemetry: telemetry contract
- GitHub/Actions + Dependabot: code, CI, dependency-update rail

durable backend는 Stage 0의 동일 failure acceptance에서 하나만 채택한다. 초기 조합은 spike 통과 전 production architecture로 간주하지 않는다.

### 교체 경계

All Tomorrow domain은 external execution을 ExecutionRef로만 참조한다.

외부 engine의 queue status, checkpoint schema, provider message object를 domain schema에 복제하지 않는다.

선택한 durable backend가 부적합해지면 PydanticAI native integration 또는 public durable backend builder 뒤의 다른 engine으로 교체할 수 있어야 한다.

### 기존 코드

기존 PipelineRuntime, Run store, WorkerAdapter를 즉시 삭제하지 않는다.

Stage 0 walking skeleton 뒤:
- 고유 가치가 있는 deterministic recipe 기능은 보존
- 외부 substrate와 중복되는 durability/retry/queue 기능은 축소
- 새 researcher path의 핵심인지 compatibility layer인지 결정

## Consequences

장점:
- commodity distributed-system code를 크게 줄인다.
- crash/restart, queue, model/tool plumbing을 검증된 프로젝트 위에서 시작한다.
- All Tomorrow 고유 기능에 개발 자원을 집중한다.

비용:
- 여러 OSS의 version/API 변화와 운영 특성을 추적해야 한다.
- adapter와 contract test가 중요해진다.
- DBOS Conductor 라이선스, Restate runtime 라이선스/운영 조건처럼 backend별 제약을 계속 감시해야 한다.
- 빠르게 변하는 upstream의 persisted compatibility 규칙을 CI로 고정해야 한다.

## Guardrails

- 같은 책임의 framework를 둘 이상 동시에 production dependency로 넣지 않는다.
- OSS 내부 DB를 중앙 canonical state로 승격하지 않는다.
- 편의를 이유로 vendor type을 core domain API에 노출하지 않는다.
- integration이 얇지 않다면 새 framework를 더 붙이기 전에 경계를 다시 검토한다.
- 외부 OSS의 라이선스와 self-host 조건을 version upgrade 때 다시 확인한다.
