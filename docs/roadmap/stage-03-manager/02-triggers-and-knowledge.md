# Stage 3.2 — Trigger & Knowledge Expansion

## Status
- 상태: 선행작업 대기
- 선행조건: 3.1 + Stage2 durable assistant
- 지금 시작 가능: 아니오

## Packets
| 순서 | 작업 | 선행조건 |
|---:|---|---|
| 3.2A | Trigger Store & Scheduler | 3.1 |
| 3.2B | Webhook / Polling / Watchers | 3.2A |
| 3.2C | Lesson Persistence & Evaluation | 3.1 |
| 3.2D | Lesson Reuse & Outcome | 3.2C |
| 3.2E | Acceptance | 3.2A~D |

파일: [02-triggers-and-knowledge/](02-triggers-and-knowledge/)

## Exit
trigger idempotency/time/restart와 lesson evidence→reuse→outcome lifecycle이 같은 provenance를 가져야 한다.
