# Stage 2 — Reliable Assistant & Remote Control

## Stage Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 1 완료
- 공통 계약:
  - ../plan-verification-contract.md
  - ../domain-contracts.md
  - ../failure-recovery-contract.md
  - ../data-security-artifact-contract.md

기존 Web/Discord/worker prototype 존재는 Stage 2 완료 증거가 아니다.

## 작업 상태판

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 |
|---:|---|---|---:|---|
| 1 | User Ingress | 선행작업 대기 | 아니오 | Stage 1 |
| 2 | Remote Control Surface | 선행작업 대기 | 아니오 | 1 + Stage 1 runtime |
| 3 | Reliable Request Execution | 선행작업 대기 | 아니오 | 1 + durable kernel |
| 4 | Routing & Cross-System Action | 선행작업 대기 | 아니오 | 3 |
| 5 | Stage Acceptance | 선행작업 대기 | 아니오 | 1~4 |

## Stage exit

어느 기기에서든 authenticated request를 맡기고, duplicate delivery·restart·NEED_USER·worker/provider failure를 견디며, 다른 client가 같은 Request/Goal/Work/Run identity와 ArtifactRefs를 이어받고 cross-system mutation까지 추적할 수 있어야 한다.
