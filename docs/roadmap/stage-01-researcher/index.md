# Stage 1 — Durable Self-Improving Researcher

## Stage Status

- 상태: **개발중**
- 지금 시작 가능: **예**
- 선행조건: 없음
- Stage 종료 조건: [06-acceptance.md](06-acceptance.md) 통과

첫 사용자 체감 제품은 스스로 공부하고, 문제를 발견하고, 자기 자신까지 개선하는 researcher다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 상태/상세 인덱스 |
|---:|---|---|---:|---|---|
| 1 | Minimal Durable Kernel | 개발중 | 예 | 없음 | [01-durable-kernel.md](01-durable-kernel.md) |
| 2 | Researcher Loop | 선행작업 대기 | 아니오 | 1 완료 | [02-researcher-loop.md](02-researcher-loop.md) |
| 3 | Evaluation & Self-Improvement | 선행작업 대기 | 아니오 | 2 완료 | [03-evaluation-self-improvement.md](03-evaluation-self-improvement.md) |
| 4 | Runtime & Tool Surface | 개발중 | 예 | 일부 병렬 가능 | [04-runtime-and-tools.md](04-runtime-and-tools.md) |
| 5 | Daily Report & Priority | 선행작업 대기 | 아니오 | 2 완료, 일부는 4 필요 | [05-report-and-priority.md](05-report-and-priority.md) |
| 6 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~5 완료 | [06-acceptance.md](06-acceptance.md) |

## 지금 바로 구현 가능한 packet

### Durable Kernel

- **01A Schema Migration**

01A가 끝난 뒤 01B, 그 뒤 01C/01D가 열린다.

### Runtime & Tools

서로 병렬 가능:

- **04A LiteLLM Gateway**
- **04B Codex Worker**
- **04C Laptop Workspace Resolver**

## 작업자가 읽는 순서

1. 이 index
2. 01 또는 04의 local index
3. 현재 packet 한 파일
4. 그 packet이 직접 요구하는 코드/ADR만 추가 확인

전체 roadmap/architecture를 매 작업마다 다시 읽지 않는다.
