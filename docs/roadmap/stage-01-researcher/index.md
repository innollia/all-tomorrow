# Stage 1 — Durable Self-Improving Researcher

## Stage Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 OSS Assembly & Architecture Proof 완료
- Stage 종료 조건: [06-acceptance.md](06-acceptance.md) 통과

기존 Stage 1 prototype과 계획은 보존하지만, 새 foundation 구현은 Stage 0 결과가 나오기 전 시작하지 않는다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 상태/상세 인덱스 |
|---:|---|---|---:|---|---|
| 1 | Minimal Durable Kernel | 선행작업 대기 | 아니오 | Stage 0 | [01-durable-kernel.md](01-durable-kernel.md) |
| 2 | Researcher Loop | 선행작업 대기 | 아니오 | 1 완료 + agent/model substrate | [02-researcher-loop.md](02-researcher-loop.md) |
| 3 | Evaluation & Self-Improvement | 선행작업 대기 | 아니오 | 2 완료 | [03-evaluation-self-improvement.md](03-evaluation-self-improvement.md) |
| 4 | Runtime & Tool Surface | 선행작업 대기 | 아니오 | Stage 0에서 integration seam 확정 | [04-runtime-and-tools.md](04-runtime-and-tools.md) |
| 5 | Daily Report & Priority | 선행작업 대기 | 아니오 | 2 완료 + runtime 일부 | [05-report-and-priority.md](05-report-and-priority.md) |
| 6 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~5 완료 | [06-acceptance.md](06-acceptance.md) |

## Stage 0가 바꿀 예정인 부분

기존 계획에서 다음은 구현 지시가 아니라 재작성 대상으로 취급한다.

- 01A의 queue/lease용 schema
- 01C custom DurableWorkQueue
- 04A custom LiteLLM HTTP client
- custom durable retry/recovery ownership
- agent/eval/telemetry의 자체 framework화

유지 가능성이 높은 것:
- Goal/Work semantic layer
- source ownership
- worker CLI adapters
- laptop workspace/Approval Authority
- parallel metacognition
- existing PipelineRuntime의 deterministic recipe 기능

## 다음 작업

[Stage 0 index](../stage-00-assembly/index.md)로 이동한다.
