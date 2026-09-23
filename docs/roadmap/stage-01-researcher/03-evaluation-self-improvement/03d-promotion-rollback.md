# 03D — Ordinary Promotion and Rollback

## Status

- 상태: **선행작업 대기**
- 선행조건: 03C 완료
- 지금 시작 가능: **아니오**

## 목적

ordinary ACCEPT candidate를 target 종류에 맞는 안전한 deployment transaction으로 promotion하고 regression 시 immutable previous version으로 rollback한다.

## Common PromotionTarget contract

- inspect_current() -> immutable ref/hash
- validate_candidate(candidate_ref)
- plan(candidate_ref, current_ref) -> DeploymentPlan
- apply(plan) -> DeploymentRef
- verify(deployment_ref)
- rollback(previous_ref, deployment_ref)
- observe(deployment_ref, monitoring_policy)

core는 target filesystem/provider detail을 모른다.

## Target classes

### Prompt/config

- immutable version create
- alias/reference switch
- smoke evaluation
- atomic/current ref 확인
- previous alias/ref rollback

### Pipeline/policy

- schema/contract compatibility 검증
- active Run과 version binding 확인
- immutable version activation
- previous version rollback

### Code/repository deploy

prompt promotion과 같은 수준으로 단순 apply하지 않는다.

필수 deployment plan:

- commit/artifact hash
- dependency lock
- migration compatibility
- in-flight durable execution compatibility
- new process/version start
- readiness/smoke
- traffic/active alias switch
- old version drain 또는 00E strategy
- rollback 가능 여부
- irreversible DB migration이 있으면 ordinary auto-promotion 금지 또는 별도 protected/migration rail

## Promotion flow

1. proposal ACCEPT
2. protection classification
3. frozen candidate/criteria hash 재검증
4. current baseline hash 재확인
5. stale면 STALE + 재평가
6. target-specific plan validate
7. apply
8. smoke/verify
9. PROMOTED Event
10. monitoring policy 시작

partial apply가 발생하면 성공으로 기록하지 않고 rollback/repair state로 남긴다.

## Monitoring policy

target마다 explicit config/ref가 필수다.

- minimum observation count and/or duration
- metrics/evidence to collect
- hard rollback signals
- tolerance/debounce
- UNKNOWN handling

숨은 default window를 두지 않는다. 정책이 없으면 automatic promotion 불가다.

테스트 fixture에서는 작은 deterministic count를 사용해도 production config와 분리한다.

## Rollback

automatic hard triggers:

- deploy/readiness failure
- hard invariant regression
- predeclared critical threshold 반복 초과

ambiguous quality decline → NEED_MORE_EVIDENCE/investigation, 즉시 rollback 여부는 policy.

rollback은 exact previous immutable ref로 복귀하고 idempotent해야 한다.

## Requirements

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 03D-01 | stale baseline blocks | race fixture | L1 |
| 03D-02 | prompt/config atomic switch+rollback | integration | L1 |
| 03D-03 | code deploy preserves/drains in-flight Run | process/version test | L2/L3 |
| 03D-04 | apply/verify failure rollback | negative integration | L1/L2 |
| 03D-05 | monitoring policy 없으면 auto-promote 실패 | unit |
| 03D-06 | repeated rollback idempotent | integration |
| 03D-07 | protected/unknown classification auto apply 불가 | negative |

## 완료조건

ordinary target마다 실제 deployment semantics가 정의되고 code deployment가 단순 file replace로 축소되지 않으며 exact rollback과 in-flight compatibility를 증명해야 한다.
