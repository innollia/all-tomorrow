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

## 2026-10-21 상태 정정

기존 부품의 존재와 단위시험을 Stage 전체 운영 완료로 표시하지 않는다. [DP7 자기개선 고리](../../dp7-loop.md)에 연결 경로와 남은 검증을 기록했다. 메타인지→영속 Work→사본 실행→시험→반영/되돌림→Event→다음 관측→보고 적재를 연결했다. 실제 DB·Discord·재부팅 검증은 확인 전이다. 서버와 실행기는 DP7, 노트북은 기록 전용이다. 기존 일일 보고 composer나 보호 변경 승인 경계 전체를 완료한 것은 아니다.
