# Stage 0 — OSS Assembly & Architecture Proof

## Stage Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- Stage 종료 조건: 00A~00E 완료

목적은 새 framework를 만드는 것이 아니다. 이미 존재하는 GitHub 프로젝트를 실제로 이어 붙여 All Tomorrow가 직접 소유해야 하는 최소 경계만 남긴다.

## 현재 우선 조합

공통 조각:

- Agent layer: PydanticAI
- Model gateway: LiteLLM Proxy
- Telemetry contract: OpenTelemetry
- Code/evaluation rail: GitHub + Actions
- 기존 All Tomorrow: Goal/Work 의미, source ownership, metacognition, authority, worker adapters

Stage 0에서는 두 결정을 분리한다.

- **Durable backend:** DBOS vs Restate
- **Tool gateway:** LiteLLM MCP Gateway 우선 spike, concrete gap이 있으면 FastMCP fallback

LiteLLM MCP가 실패해도 durable candidate를 탈락시키지 않는다. 반대도 마찬가지다.

## Durable Candidates

- **DBOS**: Python/PostgreSQL 중심, PydanticAI native durability, 얇은 single-node 시작
- **Restate**: PydanticAI SDK integration, single-binary self-host, journal/state/signals/long wait

후순위는 primary 둘이 hard gate를 못 닫을 때만 본다.

- Temporal
- Hatchet
- Prefect

production durable engine은 하나만 채택한다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 파일 |
|---:|---|---|---:|---|---|
| 00A | Substrate Spike & Selection | 개발중 | 예 | 없음 | [00a](00a-substrate-spike.md) |
| 00A-1 | Common Harness | 시작안했음 | 예 | 없음 | [00a-1](00a-1-common-harness.md) |
| 00A-2 | DBOS Spike | 선행작업 대기 | 아니오 | 00A-1 | [00a-2](00a-2-dbos-spike.md) |
| 00A-3 | Restate Spike | 선행작업 대기 | 아니오 | 00A-1 | [00a-3](00a-3-restate-spike.md) |
| 00A-4 | Tool Gateway Spike | 선행작업 대기 | 아니오 | 00A-1 | [00a-4](00a-4-gateway-spike.md) |
| 00A-5 | Selection Record | 선행작업 대기 | 아니오 | 00A-2~00A-4 | [00a-5](00a-5-selection.md) |
| 00B | Ownership & Adapter Contracts | 선행작업 대기 | 아니오 | 00A | [00b](00b-ownership-contracts.md) |
| 00C | Failure Walking Skeleton | 선행작업 대기 | 아니오 | 00A + 00B | [00c](00c-failure-walking-skeleton.md) |
| 00D | Observability / Eval / CI Seam | 선행작업 대기 | 아니오 | 00C | [00d](00d-observability-eval-ci.md) |
| 00E | Architecture Lock & Stage 1 Rewrite | 선행작업 대기 | 아니오 | 00A~00D | [00e](00e-architecture-lock.md) |

## 지금 시작할 작업

[00A-1 Common Harness](00a-1-common-harness.md)만 시작한다.

00A-1이 끝나기 전에 DBOS/Restate implementation convenience에 맞춰 harness나 domain semantics를 바꾸지 않는다.

## Stage 핵심 질문

1. 어떤 durable backend가 같은 failure harness를 더 적은 glue와 운영 상태로 통과하는가?
2. 어떤 tool gateway가 agent-side endpoint를 안정적으로 고정하면서 dynamic upstream을 제공하는가?
3. 두 선택을 결합해도 crash/recovery/privacy/telemetry가 유지되는가?
4. 선택 substrate를 제거해도 Goal/Work 의미가 유지되는가?
5. 기존 PipelineRuntime/worker adapter 중 무엇을 compatibility layer로 남길 것인가?
6. 처음부터 직접 구현해야 하는 최소 코드는 정확히 무엇인가?

답을 코드와 실패 실험으로 증명하기 전에는 Stage 1 schema를 확정하지 않는다.
