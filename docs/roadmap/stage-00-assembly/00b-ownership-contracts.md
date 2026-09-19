# 00B — Ownership & Adapter Contracts

## Status

- 상태: **선행작업 대기**
- 선행조건: 00A

## 목적

GitHub 프로젝트들을 이어 붙이되 어느 프로젝트가 어떤 진실을 소유하는지 먼저 고정한다.

## All Tomorrow가 소유

- Goal
- Work의 사용자/프로젝트 의미와 우선순위
- project/source refs
- context assembly
- metacognition decision과 lineage
- authority classification
- external execution provenance

## 외부 substrate가 소유

DBOS:
- workflow execution history
- checkpoint/recovery
- queue scheduling mechanics
- retry/concurrency/rate mechanics
- durable message/event primitive

PydanticAI:
- agent/model/tool interaction contract
- structured result validation
- MCP client/toolset plumbing
- agent-level instrumentation/eval integration

LiteLLM:
- provider-facing model gateway
- provider credentials/config
- gateway-level usage/cost/rate observations

OpenTelemetry:
- telemetry representation/transport

GitHub:
- source commits/branches/PR history

## 필요한 All Tomorrow contract

최소 interface만 만든다.

- DurableExecutionPort: start/get/cancel/signal
- AgentExecutionPort: run with typed input/output
- ModelGateway configuration: logical model alias → gateway model name
- ExecutionRef: backend, execution_id, version
- TraceLink: All Tomorrow trace/work/run ↔ external execution/span ids

DBOS queue row나 PydanticAI message object를 domain record에 직렬화하지 않는다.

## 완료조건

한 장의 ownership matrix와 위 contract를 만족하는 최소 protocol/type가 확정되고, 특정 vendor를 제거해도 Goal/Work domain type이 변하지 않는다는 테스트가 있다.
