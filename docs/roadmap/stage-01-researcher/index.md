# Stage 1 — Durable Self-Improving Researcher

## Stage Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- Stage 종료 조건: [06-acceptance.md](06-acceptance.md) 통과

첫 사용자 체감 제품은 스스로 공부하고, 문제를 발견하고, 자기 자신까지 개선하는 researcher다.

durable kernel은 제품이 아니라 researcher를 살리기 위한 선행 기반이다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 1 | Minimal Durable Kernel | 개발중 | 예 | 없음 | [01-durable-kernel.md](01-durable-kernel.md) |
| 2 | Researcher Loop | 선행작업 대기 | 아니오 | 1 완료 | [02-researcher-loop.md](02-researcher-loop.md) |
| 3 | Evaluation & Self-Improvement | 선행작업 대기 | 아니오 | 2 완료 | [03-evaluation-self-improvement.md](03-evaluation-self-improvement.md) |
| 4 | Runtime & Tool Surface | 개발중 | 예 | 일부 병렬 가능, protected promotion은 3 필요 | [04-runtime-and-tools.md](04-runtime-and-tools.md) |
| 5 | Daily Report & Priority | 선행작업 대기 | 아니오 | 2 완료, 일부는 4 필요 | [05-report-and-priority.md](05-report-and-priority.md) |
| 6 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~5 완료 | [06-acceptance.md](06-acceptance.md) |

## 병렬 가능성

현재 바로 작업 가능한 축은 두 개다.

- 01 Durable Kernel
- 04 Runtime & Tool Surface의 LiteLLM/Codex/host contract 부분

단, 04에서 protected production promotion을 실제로 켜는 일은 03과 Approval Authority가 끝난 뒤에만 가능하다.
