# Stage 3.3 — Discovery, Resources and Multi-Executor

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2 routing + Stage 3.2
- 지금 시작 가능: **아니오**
- contracts: ../data-security-artifact-contract.md

## 목적

새 tool/model/library/host를 안전하게 탐색하고 resource accounting과 multi-executor workspace를 generic metadata/policy로 운영한다.

# External discovery

observation
→ research question
→ ResearchArtifact
→ candidate source/version/hash
→ risk/usefulness/duplication review
→ bounded sandbox experiment
→ evaluation
→ registry/lesson/proposal

## Supply-chain boundary

외부 repository/README/web instruction은 untrusted input이다.

experiment 전 명시:

- source URL/ref/version/hash
- package/artifact provenance
- install/build commands to be executed
- sandbox filesystem scope
- network allow/deny
- credentials: production secret 없음
- CPU/time/output budget
- cleanup
- generated binary/artifact hash

install script가 있다는 이유로 host에서 바로 실행하지 않는다.
production 도입은 Stage 1 self-change/protected rail을 통과한다.

# Resource Pool

ResourceRecord:

- resource_id
- kind
- executor/provider/account ref
- capabilities
- authority scope
- health + observed_at
- cost model/usage ref
- quota/rate/concurrency limits
- current reservation/usage
- locality/data constraints
- quality/evaluation refs
- version

## Accounting

Stage 1 lineage budget을 복제하는 별도 accounting 체계를 만들지 않는다.

resource ledger는 **capacity/reservation/actual usage**를 제공하고 Work/lineage budget policy가 이를 소비한다.

- reservation은 atomic
- expiration/release policy
- actual usage reconcile
- failed operation도 발생한 cost 반영
- unknown quota/cost를 infinite/0으로 처리하지 않음
- concurrent reservation ceiling 초과 금지

# Multi-executor workspace

필요할 때만 확장:

executor_id + project_id
→ workspace binding/status

상태:

- unavailable
- provisioning
- ready-clean / ready-dirty
- busy
- offline
- reconciliation-required

필수:

- checkout/source identity
- branch/HEAD
- dirty/untracked observation
- allowed root
- provisioning provenance
- offline/online freshness
- mutation result/artifact/commit refs

dirty canonical checkout을 자동 reset/stash하지 않는다.

## Genericity

새 provider/tool/host 추가는 adapter + metadata + policy로 참여한다.
generic core에 if provider_name / if host_name branch를 추가하면 architecture fitness 실패다.

## Requirements

- malicious/untrusted discovery sandbox escape 실패
- production credential canary 접근 실패
- package/source hash provenance
- concurrent resource reservation ceiling
- unknown quota/cost conservative handling
- new resource adapter without core branch
- multi-executor offline/dirty reconciliation

## 완료조건

새 외부 자원 탐색부터 안전한 bounded experiment와 resource registration까지 production secret/authority를 침범하지 않고 generic core 변경 없이 수행 가능해야 한다.
