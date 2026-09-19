# Stage 0 — OSS Assembly & Architecture Proof

## Stage Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- Stage 종료 조건: 00A~00E 완료

목적은 새 framework를 만드는 것이 아니다. 이미 존재하는 GitHub 프로젝트를 실제로 이어 붙여 All Tomorrow가 직접 소유해야 하는 최소 경계만 남긴다.

## 현재 우선 조합

- Agent layer: PydanticAI
- Durable backend 첫 후보: DBOS
- Model gateway: LiteLLM Proxy
- Telemetry contract: OpenTelemetry
- Code/evaluation rail: GitHub + Actions
- 기존 All Tomorrow: Goal/Work 의미, source ownership, metacognition, authority, worker adapters

비교 후보:
- Temporal: PydanticAI가 native 지원하는 더 무거운 migration 대안
- Hatchet: embedded/self-host가 강한 task engine 대안. PydanticAI durable 연결은 별도 integration 비용을 먼저 측정

Stage 0에서 여러 durable engine을 production dependency로 동시에 넣지 않는다.

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

1. PydanticAI + DBOS + LiteLLM 조합이 현재 필수 실행 요구를 실제로 만족하는가?
2. crash/restart, duplicate start, delay/priority, HITL pause/resume가 custom queue 없이 가능한가?
3. DBOS를 제거하거나 Temporal/Hatchet 등으로 바꿔도 Goal/Work 의미는 유지되는가?
4. 기존 PipelineRuntime과 worker adapter 중 무엇을 보존하고 무엇을 compatibility layer로 내릴 것인가?
5. 처음부터 직접 구현해야 하는 최소 코드는 정확히 무엇인가?

답을 코드와 실패 실험으로 증명하기 전에는 Stage 1 schema를 확정하지 않는다.
