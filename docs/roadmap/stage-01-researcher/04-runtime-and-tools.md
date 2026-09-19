# Stage 1.4 — Runtime Placement and Tool Surface

## Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음

이 파일은 구현 상세가 아니라 **04 작업의 상태 인덱스**다.

## Packet Status

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 04A | LiteLLM Gateway | 시작안했음 | 예 | 없음 | [04a-litellm-gateway.md](04-runtime-and-tools/04a-litellm-gateway.md) |
| 04B | Codex Worker | 시작안했음 | 예 | 없음 | [04b-codex-worker.md](04-runtime-and-tools/04b-codex-worker.md) |
| 04C | Laptop Workspace Resolver | 시작안했음 | 예 | 없음 | [04c-laptop-workspace.md](04-runtime-and-tools/04c-laptop-workspace.md) |
| 04D | AWS Always-On Runtime | 선행작업 대기 | 아니오 | 01A~01C + 04A | [04d-aws-runtime.md](04-runtime-and-tools/04d-aws-runtime.md) |
| 04E | Laptop Approval Authority | 선행작업 대기 | 아니오 | Stage 1.3 | [04e-approval-authority.md](04-runtime-and-tools/04e-approval-authority.md) |

## 현재 병렬 착수 가능

- 04A LiteLLM
- 04B Codex
- 04C Laptop Workspace

세 packet은 서로 독립적으로 먼저 개발 가능.

04D는 durable queue가 생긴 뒤,
04E는 self-improvement lifecycle이 생긴 뒤 시작.

## 이미 있는 기반

- AntigravityWorker
- OpenCodeWorker
- WorkerService / WorkerAdapter
- subprocess safety helper
- ProjectRegistry
- ModelRoute / ModelRouter

기존 기반을 재사용하고 새 framework를 만들지 않는다.

## Stage 1.4 완료조건

04A~04E가 모두 필요한 시점에 완료되고, Stage 1 acceptance에서 AWS/laptop authority 경계가 실제로 검증되면 개발완료.
