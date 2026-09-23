# Stage 2.4 — Routing & Cross-System Action

## Status
- 상태: 선행작업 대기
- 선행조건: 2.3
- 지금 시작 가능: 아니오

## Packets
| 순서 | 작업 | 선행조건 |
|---:|---|---|
| 2.4A | Resource Registry | 2.3 |
| 2.4B | Selection Policy | 2.4A |
| 2.4C | Fallback & Cross-System Mutation | 2.4A + 2.4B |
| 2.4D | Acceptance | 2.4A~C |

파일은 [04-routing-cross-system/](04-routing-cross-system/) 하위.

## Exit
capability/authority/health/cost 기반 selection과 failure fallback/cross-source mutation이 provider 이름별 core branch 없이 동작해야 한다.
