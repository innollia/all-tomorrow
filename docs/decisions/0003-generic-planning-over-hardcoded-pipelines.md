# ADR 0003: Generic Planning Over Hard-coded Pipelines

Status: Accepted

Date: 2026-09-19

## Context

README의 Original Vision은 단순한 고정 workflow 실행기가 아니라, 환경이 달라져도 목표를 유지하며 스스로 작업 방식을 조정하는 중앙 시스템을 요구한다.

대표 상황:

- 무료 API/resource가 quota 또는 rate limit에 걸림
- 현재 worker/executor가 unavailable 상태가 됨
- 같은 capability를 제공하는 새로운 무료 provider가 등장함
- 새 provider 사용을 위해 가입/API key 발급 같은 사용자 action이 필요함
- 반복되는 실패를 해결할 만한 새로운 blog/repository/paper가 발견됨
- 기존보다 더 나은 orchestration/resource-management 방법을 시험할 가치가 생김

이 상황들을 pipeline마다 다음처럼 추가하면 빠르게 유지 불가능해진다.

```text
if provider == A and quota_exhausted: ...
if provider == B and rate_limit: ...
if new_image_service_X: ...
if blog_Y_found: ...
```

provider, project, failure, research source가 늘어날수록 pipeline이 세계의 모든 예외를 하드코딩한 monolith가 된다.

ADR 0002는 Goal/Work를 Pipeline보다 위에 두었지만, "누가 Plan을 만들고 환경 변화에 따라 다시 짜는가"와 "새 종류가 어떻게 core 수정 없이 들어오는가"를 별도 결정으로 고정할 필요가 있다.

## Decision

### 1. Goal과 Plan을 분리한다

- Goal은 비교적 안정적인 사용자 의도와 acceptance criteria다.
- Plan은 현재 state/policy/resource 조건에서 Goal을 달성하기 위한 versioned work graph다.
- PlanRevision은 observation 때문에 Plan을 변경한 새 version과 rationale다.

resource 하나가 사라졌다는 이유만으로 Goal을 폐기하지 않는다.

### 2. Planner / Replanner가 계획 변경을 소유한다

Planner 입력:

- Goal
- current Plan/Work state
- project context
- resource/capability snapshot
- policy/budget/permission
- observations
- reusable artifact/lesson refs

Planner 출력:

- Plan or PlanRevision candidate
- create/keep/cancel/defer WorkItem decisions
- capability/resource constraints
- NEED_USER requirements
- rationale/provenance

Planner output은 실행 명령이 아니라 candidate다. contract/dependency/permission/hard-budget/acceptance-criteria validation을 통과한 뒤에만 durable Plan/Work로 materialize한다.

Planner 구현은 rule-based, LLM, hybrid 등으로 교체 가능하다.

Pipeline은 Planner가 만든 WorkItem을 수행하는 bounded execution recipe다.

### 3. 외부 변화는 Observation과 ResourceState로 들어온다

provider-specific raw 상태를 generic semantic layer로 정규화한다.

예:

- unavailable
- capacity/quota exhausted
- rate limited
- credential or user input missing
- policy blocked
- cost/latency/quality state changed
- evaluation/result changed

세상의 모든 provider를 하나의 완벽한 schema로 강제하지 않는다. 공통 의미와 provider-specific detail/ref를 분리한다. 정확한 quota가 없는 경우 `unknown/estimated`와 source/freshness/confidence를 표현하고 실제 observation으로 갱신한다.

Planner가 provider raw error string이나 서비스 이름으로 직접 분기하지 않는다.

`NodeStatus`/`WorkerStatus` 같은 execution lifecycle enum은 작고 안정적으로 유지한다. provider별 quota/auth/capacity 상태를 status enum에 계속 추가하는 대신 Observation/ResourceState로 분리한다.

### 4. 새로운 종류는 data + adapter + capability + policy로 참여한다

새 provider/tool/executor/model을 지원하기 위한 기본 extension path:

```text
descriptor / metadata
+ capability
+ adapter or adapter profile
+ ResourceState
+ policy/evaluation data
→ generic registry
→ Planner candidate set
```

integration mode:

1. 기존 protocol/profile로 연결 가능 → metadata/config만 추가
2. generic schema-driven adapter로 연결 가능 → schema/config 추가
3. custom protocol 필요 → provider-specific adapter artifact를 별도 Work/Proposal로 구현·검증

세 번째 경우의 provider-specific 코드는 허용되지만 adapter 경계에만 둔다. 새 종류 하나를 지원할 때마다 orchestration core와 기존 pipeline을 수정해야 한다면 abstraction failure signal로 본다.

### 5. Provider-specific logic는 adapter 경계에 가둔다

범용성이 "provider별 코드가 하나도 없어야 한다"는 뜻은 아니다.

다음은 adapter에 존재할 수 있다.

- SDK/protocol invocation
- authentication format
- response parsing
- provider-specific raw error interpretation
- quota endpoint parsing
- request/response conversion

하지만 그 결과는 generic capability/resource/observation contract로 위쪽에 전달한다.

### 6. Resource shortage는 generic routing/replanning problem으로 처리한다

quota/rate-limit/health/cost 변화가 생기면 먼저 Execution Resolution이 같은 capability/quality/policy를 만족하는 equivalent resource로 transparent failover할 수 있는지 본다.

transparent failover는 read-only/idempotent work 또는 side effect 전 실패가 확실한 경우에만 허용한다. mutation 결과가 ambiguous하면 idempotency ledger/read-back/reconciliation을 먼저 수행하고, 상태를 확인할 수 없으면 NEED_USER 또는 안전한 중단으로 간다.

이 failover가 불가능하거나 범위·품질·시간·작업구조·사용자 action을 바꿔야 하면 Replanner가 policy가 허용하는 선택지를 평가한다.

예:

- cheaper/lighter model or tier
- concurrency/batch reduction
- defer low-priority work
- split WorkItem
- wait until reset/not-before
- reuse existing artifact
- NEED_USER for additional resource/credential
- stop when quality/safety constraints cannot be preserved

provider마다 별도 fallback pipeline을 만들지 않는다.

Goal/acceptance criteria를 실질적으로 낮추는 변경은 명시된 policy 없이 자동 수행하지 않는다.

### 7. 새 resource 획득도 generic lifecycle을 사용한다

```text
discovered
→ ResourceCandidate
→ capability / terms / prerequisites
→ required user action?
→ NEED_USER
→ opaque credential/resource ref
→ sandbox validation
→ evaluation
→ registry/resource-pool candidate
```

사용자에게 API key가 필요하다고 요청할 수 있지만, 발견된 모든 후보에 요청하지 않는다. 현재 capability shortage, 예상 utility, 중복, risk/terms, user effort를 먼저 평가하고 의미 있는 candidate만 NEED_USER로 승격한다. secret 값은 chat/event/lesson에 복사하지 않는다.

### 8. 외부 지식에서 시스템 개선까지도 generic lifecycle을 사용한다

```text
system observation / improvement question
→ external research
→ ResearchArtifact + claims + provenance
→ compare with current architecture
→ ImprovementProposal
→ sandbox
→ evaluation against baseline
→ promotion / rejection / reference-only
```

특정 blog URL, repository, author, site를 위한 전용 improvement pipeline을 만들지 않는다.

외부 research content는 untrusted evidence다. 내부 지시문을 실행 authority로 취급하지 않고 claims/provenance로 추출해 별도 evaluation을 거친다. 외부 code를 research 단계에서 임의 실행하지 않는다.

### 9. Hard-coded pipeline을 탐지 가능한 실패로 취급한다

다음 패턴은 architecture review에서 경고 신호다.

- provider 이름이 generic orchestration pipeline의 condition에 반복 등장
- raw provider error string으로 planner branch
- resource quota가 바뀔 때 pipeline YAML 수정 필요
- 새 tool/provider마다 core registry selection code 수정
- 동일 fallback logic가 여러 pipeline에 복제
- Goal과 Plan이 결합되어 작은 환경 변화가 전체 작업 재시작을 유발
- research source마다 별도 pipeline 생성

### 10. Stable primitives may remain coded

"하드코딩 금지"를 모든 상수와 enum 제거로 해석하지 않는다.

코드에 안정적으로 고정할 수 있는 예:

- SUCCESS / FAILED / NEED_USER 같은 lifecycle semantics
- provenance, trace, permission, secret boundary
- adapter protocol
- transactional/idempotency invariant

변화 가능한 policy/data로 분리해야 하는 예:

- provider/model/project 이름
- quota threshold/reset
- ranking/fallback/degradation preference
- research source
- provider raw error branch

현재 `CapabilityRegistry`의 고정 quality/cost/latency ranking은 초기 구현으로 인정하지만 최종 policy contract로 고정하지 않는다.

## Consequences

장점:

- provider/resource 종류가 늘어나도 generic orchestration 구조가 유지된다.
- 무료 quota 변화에 따라 장기 Goal을 보존하면서 계획을 조정할 수 있다.
- 새로운 무료 resource를 discovery/evaluation 뒤 기존 pool에 편입하기 쉽다.
- 사용자가 해야 할 가입/key 발급을 같은 NEED_USER lifecycle로 처리할 수 있다.
- 외부 architecture 연구와 self-improvement가 특정 source에 종속되지 않는다.
- Pipeline의 크기와 책임이 제한된다.

비용:

- Goal과 Work 사이에 Plan/PlanRevision 모델이 추가된다.
- resource state/observation normalization이 필요하다.
- Planner/Policy의 결정 provenance와 테스트가 필요하다.
- adapter가 provider-specific detail을 generic semantic state로 변환해야 한다.

## Guardrails

- "범용성"을 이유로 모든 provider 차이를 숨기는 거대한 추상화 하나를 만들지 않는다.
- 아직 존재하지 않는 모든 미래 provider field를 미리 schema에 넣지 않는다.
- capability가 실제로 다른 작업은 별도 pipeline/adapter를 가질 수 있다.
- 단순하고 안정적인 deterministic rule이 충분한 곳에 LLM planner를 강제하지 않는다.
- Planner는 root user-control policy, permission, hard budget ceiling을 우회할 수 없다.
- Replanner는 Goal/acceptance criteria를 조용히 약화시키지 않는다.
- 자동 가입, 약관 동의, 결제, credential 발급이 사용자 action을 요구하면 NEED_USER로 멈춘다.
