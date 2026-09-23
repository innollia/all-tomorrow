# Stage 2.1 — User Ingress

## Status
- 상태: 선행작업 대기
- 선행조건: Stage 1 완료
- 지금 시작 가능: 아니오

## Packets
| 순서 | 작업 | 선행조건 |
|---:|---|---|
| 2.1A | Request / Delivery Schema | Stage 1 |
| 2.1B | Web / API Ingress | 2.1A |
| 2.1C | Discord / CLI Ingress | 2.1A |
| 2.1D | Attachment & Escalation Policy | 2.1A |
| 2.1E | Acceptance | 2.1A~D |

파일은 [01-user-ingress/](01-user-ingress/) 하위에 둔다.

## Exit
모든 ingress가 canonical Request/Delivery contract를 사용하고 duplicate delivery, attachment, escalation, API compatibility가 실제 PostgreSQL에서 검증되어야 한다.
