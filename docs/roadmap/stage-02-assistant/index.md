# Stage 2 — Reliable Assistant & Remote Control

## Stage Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 1 완료
- 기존 prototype: Web/Discord/worker adapter 일부 존재하지만 Stage 2 완료로 간주하지 않음

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 읽을 파일 |
|---:|---|---|---:|---|---|
| 1 | User Ingress | 선행작업 대기 | 아니오 | Stage 1 완료 | [01-user-ingress.md](01-user-ingress.md) |
| 2 | Remote Control Surface | 선행작업 대기 | 아니오 | 1 + Stage 1 runtime | [02-remote-control.md](02-remote-control.md) |
| 3 | Reliable Request Execution | 선행작업 대기 | 아니오 | 1 + Stage 1 durable kernel | [03-request-execution.md](03-request-execution.md) |
| 4 | Routing & Cross-System Action | 선행작업 대기 | 아니오 | 3 완료 | [04-routing-cross-system.md](04-routing-cross-system.md) |
| 5 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~4 완료 | [05-acceptance.md](05-acceptance.md) |

## Stage Exit

어느 기기에서든 사용자가 일을 맡기고, 중단·질문·재시작을 견디며, 다른 client에서도 같은 Goal/Work 상태를 이어받을 수 있어야 한다.
