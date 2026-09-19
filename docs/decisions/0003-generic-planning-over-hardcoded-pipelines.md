# ADR 0003: Generic Planning Over Hard-coded Pipelines

Status: Accepted

Date: 2026-09-19

## Context

All Tomorrow는 provider, project, quota 상태, research source가 늘어날 때마다 Pipeline이나 orchestration core에 조건문을 추가하는 구조를 피해야 한다.

잘못된 방향:

```text
if provider == A and quota_exhausted: ...
if provider == B and rate_limited: ...
if new_service_X: ...
if blog_Y_found: ...
```

이런 방식은 처음엔 빠르지만 시간이 갈수록 Pipeline이 세계의 예외 목록이 된다.

## Decision

### 1. Goal과 Plan을 분리한다

- **Goal**: 비교적 안정적인 사용자 의도와 성공 조건
- **Plan**: 현재 context, policy, resource 상태에서 Goal을 달성하기 위한 Work 구성
- 환경이 바뀌면 Goal을 버리는 대신 Plan을 새 version으로 바꿀 수 있다.
- 이미 성공한 Work와 Artifact는 가능한 한 보존한다.

별도 revision class/table은 요구하지 않는다. versioned Plan data면 충분할 수 있다.

### 2. Planner와 Execution Resolution을 분리한다

Planner는 "무슨 Work가 필요한가"를 정한다.

Execution Resolution은 "그 Work를 지금 어떤 concrete worker/tool/resource로 실행할까"를 정한다.

- 동등한 resource로의 단순 failover → Execution Resolution
- 범위, 품질, 시간, 작업 구조, 사용자 action이 달라지는 변화 → Planner
- Pipeline → 선택된 Work를 수행하는 bounded recipe

Planner는 rule-based, LLM, hybrid 중 어떤 구현도 가능하다.

Planner output은 실행 권한이 아니다. policy, permission, hard budget, dependency, acceptance criteria 검증을 통과한 뒤 Work로 materialize한다.

### 3. 외부 상태 변화는 generic 의미로 올린다

Provider별 raw error를 Planner가 직접 해석하지 않는다.

예:

```text
quota exhausted
rate limited
resource unavailable
credential/user action required
quality/cost/latency changed
```

Provider adapter는 raw detail을 보존하면서 위쪽에는 공통 의미를 전달한다.

이 공통 의미를 위해 새 subsystem을 강제하지 않는다.

- Observation은 Event metadata일 수 있다.
- Resource state는 registry metadata일 수 있다.
- Policy는 versioned config일 수 있다.

정확한 quota를 제공하지 않는 provider는 unknown/estimated + freshness 정도만 표현해도 된다.

### 4. 새 종류는 core branch보다 adapter + metadata로 들어온다

기본 extension path:

```text
capability + metadata + adapter/config + resource state
→ registry candidate
→ existing planner/execution flow
```

이미 지원하는 protocol이면 config/metadata만으로 연결할 수 있다.

새 protocol이 필요하면 provider-specific adapter 코드를 추가할 수 있다. 단, 그 코드는 adapter 경계에 두고 Planner/Pipeline에 provider 이름별 분기를 만들지 않는다.

Capability도 닫힌 enum으로 만들지 않는다. 필요한 의미를 descriptor/metadata로 확장 가능하게 둔다.

### 5. Resource shortage는 failover 또는 replanning으로 처리한다

Quota, rate limit, health 문제가 생기면:

1. 같은 capability/quality/policy를 만족하는 동등 resource가 있으면 safe failover
2. 없으면 policy에 따라 작업 축소, 병렬성 감소, 연기, 분할, wait, 추가 resource 요청 등을 Plan 변경 후보로 검토
3. Goal/acceptance criteria를 실질적으로 낮춰야 하면 명시적 policy가 없는 한 NEED_USER

Mutation의 side effect 발생 여부가 불명확하면 다른 resource로 즉시 재실행하지 않는다. idempotency/read-back/reconcile을 먼저 수행한다.

### 6. 새 무료 resource 획득도 generic lifecycle을 사용한다

새 free-tier API가 발견됐다고 전부 사용자에게 key를 요구하지 않는다.

먼저 capability shortage, 중복, 예상 효용, free quota, risk/terms, user effort를 평가한다.

가치가 있을 때만 NEED_USER로 가입/key 발급을 요청한다.

Raw secret을 chat/event에 받지 않고 external secret owner에 등록한 뒤 opaque credential reference만 중앙에서 사용한다.

### 7. 외부 연구도 generic improvement lifecycle을 사용한다

```text
system problem / question
→ external research
→ evidence + provenance
→ improvement proposal
→ sandbox/evaluation
→ promote / reject
```

특정 blog, repository, author를 위한 전용 Pipeline을 만들지 않는다.

외부 글과 repository 내용은 **untrusted evidence**다. 그 안의 지시문을 system instruction처럼 실행하지 않는다.

### 8. Hardcoding boundary

코드에 안정적으로 둘 수 있는 것:

- SUCCESS / FAILED / NEED_USER 같은 lifecycle semantics
- provenance/trace
- permission/secret boundary
- adapter interface
- transaction/idempotency invariant

Generic core에 이름별로 박지 말아야 하는 것:

- provider/model/project 이름
- quota 숫자와 reset policy
- ranking/fallback/degradation preference
- research source
- provider raw error string

현재 `CapabilityRegistry`의 고정 quality/cost/latency ranking과 pipeline-local worker-selection policy는 초기 구현이며 최종 architecture contract가 아니다.

## Acceptance Rule

새 provider/resource/tool을 fixture로 추가했을 때:

- 기존 generic Pipeline과 Planner core를 수정하지 않는가
- adapter/config/metadata 등록으로 후보가 되는가
- quota/health 변화가 provider 이름별 분기 없이 처리되는가
- 동등 failover와 실제 replanning이 구분되는가
- no-resource 상황이 곧바로 Goal failure가 되지 않는가

이 조건을 만족하지 못하면 "기능은 동작하지만 범용 구조는 실패"로 본다.

## Guardrails

- 범용성을 이유로 거대한 추상화 하나를 만들지 않는다.
- 개념 하나마다 새 class/table/service를 만들지 않는다.
- 아직 없는 모든 미래 provider를 미리 모델링하지 않는다.
- deterministic rule이 충분한 곳에 LLM Planner를 강제하지 않는다.
- Planner는 root user-control policy, permission, hard budget을 우회할 수 없다.
