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
- Model + MCP gateway: LiteLLM Proxy의 두 public surfaces를 한 service로 사용
- Telemetry contract: OpenTelemetry
- Code/evaluation rail: GitHub + Actions
- 기존 All Tomorrow: Goal/Work 의미, source ownership, metacognition, authority, worker adapters

Durable backend는 Stage 0에서 둘을 같은 acceptance로 경쟁시킨다.

- **DBOS**: Python/PostgreSQL 중심, PydanticAI native durability, 매우 얇은 single-node 시작
- **Restate**: PydanticAI integration, single-binary self-host, durable state/RPC/signals/flow-control까지 넓은 substrate

후순위 비교:
- FastMCP: LiteLLM MCP Gateway가 실제 요구를 못 닫을 때만 MCP aggregation fallback. background task/Docket 기능은 사용하지 않음
- Temporal: PydanticAI native 지원, 가장 성숙하지만 초기 운영 중량이 큼
- Hatchet: 100% MIT, Postgres/embedded/self-host와 UI가 강함. PydanticAI per-model/tool durability에는 custom backend 또는 다른 glue가 필요
- Prefect: PydanticAI native 지원 + Apache 2.0 self-host, 그러나 All Tomorrow 초기 요구보다 workflow platform 면적이 넓을 수 있음

Stage 0에서 production durable engine은 하나만 채택한다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 파일 |
|---:|---|---|---:|---|---|
| 00A | Substrate Spike & Selection | 개발중 | 예 | 없음 | [00a](00a-substrate-spike.md) |
| 00B | Ownership & Adapter Contracts | 선행작업 대기 | 아니오 | 00A | [00b](00b-ownership-contracts.md) |
| 00C | Failure Walking Skeleton | 선행작업 대기 | 아니오 | 00A + 00B | [00c](00c-failure-walking-skeleton.md) |
| 00D | Observability / Eval / CI Seam | 선행작업 대기 | 아니오 | 00C | [00d](00d-observability-eval-ci.md) |
| 00E | Architecture Lock & Stage 1 Rewrite | 선행작업 대기 | 아니오 | 00A~00D | [00e](00e-architecture-lock.md) |

## 핵심 질문

Stage 0는 다음 질문만 닫는다.

1. PydanticAI + DBOS와 PydanticAI + Restate 중 어느 조합이 현재 필수 실행 요구를 더 적은 glue로 만족하는가?
2. crash/restart, duplicate start, delay/priority, HITL pause/resume가 custom queue 없이 가능한가?
3. 선택한 durable backend를 제거하거나 다른 backend로 바꿔도 Goal/Work 의미는 유지되는가?
4. 기존 PipelineRuntime과 worker adapter 중 무엇을 보존하고 무엇을 compatibility layer로 내릴 것인가?
5. 처음부터 직접 구현해야 하는 최소 코드는 정확히 무엇인가?

답을 코드와 실패 실험으로 증명하기 전에는 Stage 1 schema를 확정하지 않는다.
