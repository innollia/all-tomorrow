# Stage 2.2 — Remote Control Surface

## Status
- 상태: 선행작업 대기
- 선행조건: 2.1 + Stage 1 runtime
- 지금 시작 가능: 아니오

## Packets
| 순서 | 작업 | 선행조건 |
|---:|---|---|
| 2.2A | Authentication & Session | 2.1 |
| 2.2B | Store-backed Control API | 2.2A + 2.1 |
| 2.2C | Backup / Restore | Stage1 AWS + 2.2A |
| 2.2D | Outbound Delivery Surface | 2.2A |

파일은 [02-remote-control/](02-remote-control/) 하위.

## Exit
remote HTTPS control, auth/session isolation, backup/restore, outbound delivery가 canonical state와 연결되어야 한다.
