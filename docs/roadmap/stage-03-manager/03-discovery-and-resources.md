# Stage 3.3 — Discovery, Resources & Multi-Executor

## Status
- 상태: 선행작업 대기
- 선행조건: Stage2 routing + 3.2
- 지금 시작 가능: 아니오

## Packets
| 순서 | 작업 | 선행조건 |
|---:|---|---|
| 3.3A | External Discovery Sandbox | Stage2 routing |
| 3.3B | Resource Ledger | 3.2 |
| 3.3C | Multi-Executor Workspace | 3.3B + Stage2 workspace |
| 3.3D | Acceptance | 3.3A~C |

파일: [03-discovery-and-resources/](03-discovery-and-resources/)

## Exit
untrusted discovery, capacity accounting, multi-executor operation이 production credential과 generic core를 침범하지 않아야 한다.
