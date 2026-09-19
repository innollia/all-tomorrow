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

선택된 Durable Backend(DBOS 또는 Restate):
- durable execution history/journal
- checkpoint/recovery
- scheduling/flow-control mechanics
- backend-level retry/concurrency primitives
- durable signal/message/wait primitive

PydanticAI:
- agent/model/tool interaction contract
- structured result validation
- MCP client/toolset plumbing
- agent-level instrumentation/eval integration

LiteLLM:
- provider-facing model gateway
- provider credentials/config
- gateway-level usage/cost/rate observations

FastMCP gateway:
- upstream MCP connection/proxy/composition
- tool namespace aggregation
- tool discovery surface
- transport/auth proxy mechanics

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
- ExecutionAttempt identity: existing run_id를 재사용할 수 있으며 Work 1:N attempt를 유지
- TraceLink: All Tomorrow trace/work/run ↔ external execution/span ids

DBOS queue row나 PydanticAI message object를 domain record에 직렬화하지 않는다.

## Cross-store consistency

application DB와 durable backend system DB를 하나의 distributed transaction으로 묶지 않는다.

대신:
1. application DB에 Work + Run/ExecutionAttempt를 먼저 commit
2. run_id를 external workflow idempotency key로 사용
3. durable backend start/enqueue
4. ExecutionRef attach
5. 2와 4 사이 crash가 나면 STARTING/no-ref attempt를 같은 run_id로 다시 start하여 기존 execution handle을 회수

reconciliation은 queue implementation이 아니라 cross-store delivery 복구 seam이다.

## 완료조건

한 장의 ownership matrix와 위 contract를 만족하는 최소 protocol/type가 확정되고, 특정 vendor를 제거해도 Goal/Work domain type이 변하지 않는다는 테스트가 있다.


## Failure Ownership Matrix

같은 실패를 여러 층이 동시에 "친절하게" retry하지 않는다.

| 실패 | 주된 owner | 보조층 |
|---|---|---|
| provider transient/rate limit | LiteLLM 또는 durable model operation 중 하나를 spike로 결정 | 나머지는 bounded/disabled |
| durable process crash | selected durable backend | All Tomorrow는 semantic reconciliation만 |
| duplicate ingress/start | run_id + durable backend idempotency | All Tomorrow dedup projection |
| tool transport transient | durable tool operation | gateway는 transport normalization |
| tool external side effect ambiguity | tool adapter idempotency/reconciliation | durable engine은 무작정 재실행하지 않음 |
| user wait | durable signal/promise | All Tomorrow question projection |
| Goal-level failure/replan | All Tomorrow | backend Run 실패는 evidence |
| dependency/API incompatibility | CI contract/replay tests | automatic merge 금지 |

Retry 횟수/timeout/backoff는 한 파일에서 policy로 조립하고 provider+LiteLLM+PydanticAI+backend에 독립적으로 기본값을 켜두지 않는다.

## Tool Gateway Boundary

PydanticAI에는 가능한 한 stable `all-tomorrow-tools` MCP endpoint 하나를 등록한다.

FastMCP가 upstream composition/proxy를 담당하고 All Tomorrow가 소유하는 것은:
- 어떤 upstream/tool을 노출할지의 policy
- project/user authority에 따른 filter decision
- source/provenance metadata

FastMCP 내부 registry를 canonical Tool Registry로 취급하지 않는다.
