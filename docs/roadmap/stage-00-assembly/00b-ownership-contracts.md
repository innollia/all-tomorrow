# 00B — Ownership & Adapter Contracts

## Status

- 상태: **선행작업 대기**
- 선행조건: 00A
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

## 목적

Stage 0 spike 결과를 바탕으로 각 계층의 소유권, identity, adapter contract, retry/reconciliation 책임을 확정한다.
00B는 "나중에 정할 것"을 남기는 문서가 아니다. 00C가 실제 failure skeleton을 구현할 수 있도록 semantic contract를 닫는 단계다.

## Ownership matrix

### All Tomorrow

- Goal / Work / Run의 semantic identity와 state
- Request/Trigger/Question/Artifact logical refs
- project/source refs와 owner-aware context assembly
- user/project priority와 budget meaning
- metacognition decision과 lineage
- authority classification
- external execution provenance와 reconciliation intent

### Selected durable backend

- durable execution history/journal
- checkpoint/recovery
- scheduling/flow-control mechanics
- backend-level concurrency primitive
- durable signal/message/wait primitive
- adapter contract에서 명시적으로 위임한 retry mechanics

### PydanticAI

- agent/model/tool interaction contract
- typed result validation
- MCP client/toolset plumbing
- agent/model/tool semantic instrumentation seam

### LiteLLM Proxy

LiteLLM과 LiteLLM Proxy를 별도 authority처럼 이중 표기하지 않는다. Stage 0 production boundary에서는 Proxy runtime 하나의 책임으로 기록한다.

- provider-facing model gateway
- provider credentials/config
- provider/model routing
- gateway-level usage/cost/rate observations
- 선택 시 MCP upstream aggregation/transport/auth

### Optional FastMCP

LiteLLM MCP Gateway가 00A acceptance를 닫지 못해 fallback으로 선택된 경우에만 tool gateway transport/delegation 책임을 가진다.
선택되지 않았다면 후속 계획에서 production component처럼 취급하지 않는다.

### OpenTelemetry

- telemetry context representation/propagation/export contract
- domain truth나 audit truth를 소유하지 않음

### GitHub

- source commits/branches/PR history
- deployment approval authority를 소유하지 않음

## Canonical identity

[Canonical Domain Contracts](../domain-contracts.md)를 그대로 사용한다.

- Work 1:N Run
- Run = 하나의 logical execution attempt
- 같은 Run의 crash/restart/reconciliation은 새 Run이 아님
- 새 retry/replan attempt는 새 run_id
- ExecutionRef는 **Run에 attach**
- Work에는 단일 ExecutionRef를 두지 않음
- Run 1:1 logical external durable execution
- agent/model invocation은 Run 아래 provenance ref로 연결

## Required ports

### DurableExecutionPort

최소 operation:

- start(run_id, execution_spec, idempotency_key, priority, delay) -> ExecutionRef
- get(execution_ref | run_id) -> ExecutionSnapshot | NotFound
- cancel(execution_ref) -> CancelResult
- signal(execution_ref, topic, signal_id, payload_ref) -> SignalResult
- result(execution_ref) -> Pending | TerminalResult

필수 semantic contract:

1. 같은 run_id/idempotency key start 재호출은 새 logical execution을 만들지 않는다.
2. NotFound와 BackendUnavailable을 같은 오류로 합치지 않는다.
3. terminal execution cancel은 idempotent already-terminal 결과다.
4. cancel request와 실제 cancellation 완료를 구분한다.
5. 동일 signal_id 재전송은 같은 signal을 두 번 적용하지 않는다.
6. result가 아직 없으면 fabricated empty result 대신 Pending을 반환한다.
7. backend internal status/type은 port 밖 domain contract로 누출하지 않는다.

### AgentExecutionPort

최소:

- run(typed_input, model_route, toolset_ref, trace_context) -> typed_output + usage/provenance

필수:

- malformed structured output은 mutation 가능한 정상 결과로 보정하지 않음
- raw provider object는 domain record에 저장하지 않음
- selected retry owner 외의 독립 retry는 disabled/bounded

### Model route

logical model alias -> LiteLLM gateway model name.
provider 이름별 branch를 domain/core에 추가하지 않는다.

## Cross-store start/reconciliation

[failure-recovery-contract.md](../failure-recovery-contract.md)의 protocol을 따른다.

추가 00B 결정:

- STARTING Run은 application DB에 먼저 commit
- run_id는 deterministic external identity의 canonical source
- ExecutionRef attach는 Run revision/CAS로 보호
- concurrent reconciler가 다른 ExecutionRef를 발견하면 invariant violation
- reconciliation retry budget을 retry policy에 포함
- 영구 reconciliation 실패는 성공처럼 숨기지 않고 repair-required/failed evidence로 남김

## Retry ownership closure

00B 완료 전에 아래 표의 "결정"을 실제 00A 선택 결과에 맞춰 채운다.

| Failure class | Primary retry owner | Disabled/bounded layers | Exhausted result |
|---|---|---|---|
| provider transient/rate limit | **00B에서 확정 필수** | provider SDK / LiteLLM / PydanticAI / durable op 중 나머지 | Run evidence + policy result |
| model timeout | **00B에서 확정 필수** | 중복 retry 금지 | retry exhausted 또는 replan |
| tool transport transient | durable tool operation 또는 gateway 중 하나 확정 | 나머지 bounded/disabled | tool failure evidence |
| worker timeout | All Tomorrow execution policy + durable operation 경계 확정 | worker 내부 무한 retry 금지 | Run failure/replan candidate |
| durable process crash | selected durable backend | All Tomorrow는 semantic reconciliation만 | recovered execution 또는 explicit invariant failure |
| external effect ambiguity | tool adapter reconciliation | durable engine blind replay 금지 | UNKNOWN/NEED_USER/repair |
| duplicate ingress/start | request/run idempotency + backend idempotency | 새 mutation 금지 | existing identity 반환 |

각 row에는 max attempts/budget, timeout, backoff, telemetry field까지 policy 파일에서 정한다.

## Tool Gateway boundary

PydanticAI에는 가능한 한 stable all-tomorrow-tools endpoint 하나를 등록한다.

All Tomorrow 소유:

- upstream/tool exposure policy
- project/user authority filter decision
- source/provenance metadata
- canonical tool identity/ref

Gateway 소유:

- MCP transport/auth
- upstream aggregation
- protocol normalization

gateway registry를 canonical Tool Registry로 취급하지 않는다.

## Requirements

| ID | 요구 | 최소 증거 |
|---|---|---|
| B-ID-01 | Work/Run/ExecutionRef canonical identity가 schema/type 계획 전체에서 일치 | L0 contract/schema test |
| B-PORT-01 | DurableExecutionPort 정상/오류/idempotency semantics 구현 가능 | L0 fake adapter contract |
| B-PORT-02 | alternate/fake adapter가 vendor type 없이 같은 contract 통과 | L0 |
| B-REC-01 | cross-store reconciliation algorithm과 concurrency conflict가 명시됨 | L0 state-machine test |
| B-RETRY-01 | 모든 주요 failure class의 primary retry owner가 하나로 확정됨 | policy snapshot + test |
| B-GW-01 | model/tool gateway authority 중복 없음 | ownership fitness test |
| B-DATA-01 | external object를 Goal/Work/Run canonical state로 직렬화하지 않음 | architecture test |
| B-TRACE-01 | Work→Run→ExecutionRef→agent/tool provenance 연결 가능 | L0 schema/fixture |

## 완료조건

다음을 모두 만족해야 한다.

1. 위 requirement 전부 evidence 확보
2. retry ownership table에 미결정 셀이 없음
3. 00A winner/version에 맞춘 concrete mapping 문서가 존재
4. vendor를 제거한 fake adapter contract가 통과
5. Stage 1의 identity/schema 계획이 이 문서와 모순되지 않도록 rewrite 대상이 명확함

## Downstream 산출물

00C가 그대로 소비할 수 있는 확정 산출물:

- identity/state contract
- DurableExecutionPort / AgentExecutionPort semantics
- retry policy
- reconciliation algorithm
- gateway ownership
- artifact/security boundary
