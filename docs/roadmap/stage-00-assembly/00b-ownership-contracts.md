# 00B — Ownership & Adapter Contracts

## Status
- 상태: **개발완료**
- 선행조건: 00A
- 지금 시작 가능: **—**
- 입력: [00A 선택 기록](00a-5-selection.md)

## 목적
00A 결과를 받아 identity/state, adapter ports, cross-store delivery, retry, tool/worker authorization을 실제 구현 단위로 잠근다.

## Subpackets

| 순서 | 작업 | 상태 | 지금 시작 가능 | 선행조건 | 파일 |
|---:|---|---|---:|---|---|
| 00B-1 | Domain Identity & State Lock | 개발완료 | — | 00A | [00b-1](00b-ownership-contracts/00b-1-domain-identity-state.md) |
| 00B-2 | Adapter Ports & Error Semantics | 개발완료 | — | 00B-1 + 00A evidence | [00b-2](00b-ownership-contracts/00b-2-adapter-ports-errors.md) |
| 00B-3 | Delivery & Reconciliation Protocol | 개발완료 | — | 00B-1 | [00b-3](00b-ownership-contracts/00b-3-delivery-reconciliation.md) |
| 00B-4 | Retry, Timeout & Replan Policy | 개발완료 | — | 00B-2 + 00A results | [00b-4](00b-ownership-contracts/00b-4-retry-timeouts-budget.md) |
| 00B-5 | Tool / Worker / Authorization Boundary | 개발완료 | — | 00B-2 + gateway result | [00b-5](00b-ownership-contracts/00b-5-tool-worker-authorization.md) |
| 00B-6 | Contract Acceptance | 개발완료 | — | 00B-1~5 | [00b-6](00b-ownership-contracts/00b-6-acceptance.md) |

## 공통 계약
- ../control-plane-contracts.md
- ../delivery-consistency-contract.md
- ../failure-recovery-contract.md
- ../operations-security-contract.md
- ../data-security-artifact-contract.md
- ../plan-verification-contract.md

## Stage 1 handoff
00B 완료 시 Stage 1이 추측 없이 소비할 산출물:
- canonical identities/state transitions
- CompletionEvidence/Event/Error/Source contracts
- DurableExecutionPort/AgentExecutionPort/Tool/Worker contracts
- DeliveryRecord/outbox/reconciliation protocol
- exact retry/timeout/replan policy
- authorization/tool registry boundary

미정 retry owner나 active-Run semantics가 남으면 00B 완료 금지.
