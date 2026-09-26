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

Stage 1 계획은 공통 contract 수준까지 구체화되어 있고, selected substrate/version/mapping은 [ADR 0006 — Stage 0 Architecture Lock](../../decisions/0006-stage0-architecture-lock.md)에서 실제 spike 결과로 확정됐다(아래 표). Stage 0가 개발완료로 전이되기 전에는 구현하지 않는다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 상태/상세 인덱스 |
|---:|---|---|---:|---|---|
| 1 | Minimal Durable Kernel | 선행작업 대기 | 아니오 | Stage 0 | [01-durable-kernel.md](01-durable-kernel.md) |
| 2 | Researcher Loop | 선행작업 대기 | 아니오 | 1 + 04A | [02-researcher-loop.md](02-researcher-loop.md) |
| 3 | Evaluation & Self-Improvement | 선행작업 대기 | 아니오 | 2 | [03-evaluation-self-improvement.md](03-evaluation-self-improvement.md) |
| 4 | Runtime & Tool Surface | 선행작업 대기 | 아니오 | Stage 0 | [04-runtime-and-tools.md](04-runtime-and-tools.md) |
| 5 | Daily Report & Priority | 선행작업 대기 | 아니오 | 1 + 2 + runtime | [05-report-and-priority.md](05-report-and-priority.md) |
| 6 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~5 | [06-acceptance.md](06-acceptance.md) |

## 00E에서 확정된 값 (placeholder 해소 완료)

아래 값은 [ADR 0006 — Stage 0 Architecture Lock](../../decisions/0006-stage0-architecture-lock.md)에서 실제 Stage 0 evidence로 확정됐다. Stage 1 packet은 이 값을 추측하지 않고 참조한다.

| placeholder | 확정 값 | 근거 |
|---|---|---|
| selected durable backend/version/package/runtime | DBOS 3.0.0, package 소비, Python worker + application PostgreSQL(별도 durable 서버 없음) | D-LOCK-01 |
| run_id→external execution mapping | `work_id:run_id`; ExecutionRef는 Run 소유(Work에 두지 않음) | D-LOCK-02 |
| retry owner/attempt/timeout/backoff | 유일 자동 retry owner = DBOS model step(최대 6회, 2초 간격); SDK/LiteLLM/semantic retry 0 | D-LOCK-04, D-LOCK-05 |
| priority/delay/signal/cancel mapping | semantic priority → adapter가 backend priority로 변환; typed wait/signal payload; 구체 수치는 01A~01C에서 store와 확정 | D-LOCK-06 |
| history upgrade/replay-or-drain strategy | 호환 변경 = replay, 비호환 = 새 버전 분리 후 drain(expectation 덮어쓰기 금지) | D-LOCK-03 |
| model/tool gateway selection | LiteLLM Proxy 1.101.0(model+fixed MCP 겸용); FastMCP fallback 불필요 | D-LOCK-07, D-LOCK-08 |
| PipelineRuntime disposition | compatibility-only(중복 durability/retry/queue 축소, recipe 가치는 보존) | D-LOCK-12 |
| AWS process topology | 단일 노드 worker + PostgreSQL + 별도 LiteLLM Proxy; image digest pin(latest 금지); L3 인증은 04D | D-LOCK-13 |
| journal/gateway/artifact retention | journal 7일(active/waiting 제외), LiteLLM logging off, artifact CAS + ArtifactRef만 App DB | D-LOCK-09~11 |
| protected credential boundary | AWS runtime env/config에 protected credential 금지(fitness test 강제); threat model은 04E | D-LOCK-14 |

placeholder가 모두 해소됐으므로, Stage 0가 개발완료로 전이되면 Stage 1 packet은 위 값을 근거로 착수할 수 있다.

## Stage 1에서 재구현하지 않는 것

- custom durable queue/lease/heartbeat/requeue
- custom crash recovery engine
- provider별 model client
- backend internal state를 canonical domain으로 복제
- target/provider 이름별 generic-core branch

## 다음 작업

Stage 0가 개발완료되기 전에는 [Stage 0 index](../stage-00-assembly/index.md)를 따른다.
