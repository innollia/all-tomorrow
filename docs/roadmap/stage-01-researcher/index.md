# Stage 1 — Durable Self-Improving Researcher

## Stage Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 OSS Assembly & Architecture Proof 완료
- Stage 종료 조건: [06-acceptance.md](06-acceptance.md) 통과
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

Stage 1 계획은 현재 공통 contract 수준까지 구체화되어 있지만, 00E에서 selected substrate/version/mapping을 실제 spike 결과로 채우기 전에는 구현하지 않는다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 상태/상세 인덱스 |
|---:|---|---|---:|---|---|
| 1 | Minimal Durable Kernel | 선행작업 대기 | 아니오 | Stage 0 | [01-durable-kernel.md](01-durable-kernel.md) |
| 2 | Researcher Loop | 선행작업 대기 | 아니오 | 1 + 04A | [02-researcher-loop.md](02-researcher-loop.md) |
| 3 | Evaluation & Self-Improvement | 선행작업 대기 | 아니오 | 2 | [03-evaluation-self-improvement.md](03-evaluation-self-improvement.md) |
| 4 | Runtime & Tool Surface | 선행작업 대기 | 아니오 | Stage 0 | [04-runtime-and-tools.md](04-runtime-and-tools.md) |
| 5 | Daily Report & Priority | 선행작업 대기 | 아니오 | 1 + 2 + runtime | [05-report-and-priority.md](05-report-and-priority.md) |
| 6 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~5 | [06-acceptance.md](06-acceptance.md) |

## 00E가 채워야 하는 placeholders

다음은 설계 방향이 아니라 **Stage 0 evidence로 concrete value를 넣어야 하는 자리**다.

- selected durable backend/version/package/runtime
- run_id→external execution mapping
- retry owner/attempt/timeout/backoff
- priority/delay/signal/cancel mapping
- history upgrade/replay-or-drain strategy
- model/tool gateway selection
- PipelineRuntime disposition
- AWS process topology
- journal/gateway/artifact retention
- protected credential boundary

이 값이 미정이면 해당 packet은 시작 불가다.

## Stage 1에서 재구현하지 않는 것

- custom durable queue/lease/heartbeat/requeue
- custom crash recovery engine
- provider별 model client
- backend internal state를 canonical domain으로 복제
- target/provider 이름별 generic-core branch

## 다음 작업

Stage 0가 개발완료되기 전에는 [Stage 0 index](../stage-00-assembly/index.md)를 따른다.
