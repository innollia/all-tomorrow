# Stage 1.6 — Acceptance

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01~05 완료
- contract: ../plan-verification-contract.md

## Environment gate matrix

| Area | 최소 level |
|---|---|
| domain/schema/evaluator pure rules | L0 |
| PostgreSQL/durable/model gateway integration | L1 |
| process kill/restart/version replay | L2 |
| AWS reboot/backup/remote runtime | L3 |
| laptop Approval Authority security boundary | L3 |

낮은 level mock으로 높은 level requirement를 대체하지 않는다.

## Required axes

- real PostgreSQL
- selected durable backend
- process kill/restart
- duplicate start/idempotency
- NEED_USER restart
- model gateway outage
- worker timeout
- V1→V2 in-flight strategy
- OTel/provenance
- eval regression
- sandbox/promotion/rollback
- protected laptop authority
- report/time/priority
- backend 내부 상태 없이 Goal/Work/Run 의미 설명 가능
- ArtifactRef/data retention/privacy contract

## Backend escape

fake/alternate adapter contract suite가 selected backend internal type leakage를 탐지해야 한다.
두 번째 backend production 배포는 필수 아님.

## Stage completion rule

각 하위 packet requirement matrix와 06B scenario가 요구 evidence level로 모두 닫혀야 한다.
"전체 pytest 통과" 하나만으로 Stage 완료를 주장하지 않는다.
