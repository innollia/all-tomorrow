# 04G — Secrets, Operational Alerts & Dependency Security

## Status
- 상태: 선행작업 대기
- 선행조건: Stage 0 + 04D topology
- 지금 시작 가능: 아니오

## 목적
operations-security-contract.md를 실제 deployment 계획으로 내린다.

## 예정 위치
- deployment/secret configuration
- ops/runbooks/
- dependency/security workflow **계획**
- tests/security/ 및 deployed acceptance

이 계획 작업에서는 workflow/code를 생성하지 않는다.

## Secret backend
00E/04D에서 AWS ordinary runtime secret backend를 하나 확정.
Laptop Approval Authority secret domain은 별도.

각 secret:
- id/ref
- consumer
- read permission
- rotation/revocation
- reload/restart behavior
- last rotated metadata
- audit

## Alerts
최소:
- reconciliation stuck
- REPAIR_REQUIRED
- repeated Run/replan storm
- durable/model/tool unavailable
- backup stale/fail
- storage pressure
- trigger/report missed
- auth/approval attack threshold

각 alert에 metric/query, threshold/window, severity, destination, runbook.

## Dependency security
향후 CI 계획:
- vulnerability scan
- SBOM
- license inventory
- lockfile/image digest
- update provenance
- high-risk install/build script sandbox review

## Requirements
- S1-04G-01 production secret plaintext persistence 0
- S1-04G-02 rotation/revocation runbook
- S1-04G-03 alert path 하나 실제 L3 검증
- S1-04G-04 backup failure alert
- S1-04G-05 dependency security artifacts
- S1-04G-06 security update도 durable compatibility gate 우회 금지
