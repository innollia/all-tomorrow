# Architecture

이 문서는 README의 최종 목적을 기술 구조로 번역한다. README의 Original Vision과 충돌하면 이 문서를 수정한다.

현재 구현은 아래 목표 구조의 일부만 존재한다. 구현된 것과 목표 경계를 섞어 "이미 완성됨"으로 서술하지 않는다.

## 1. Target System Shape

All Tomorrow의 중앙 authority는 모든 실행과 모든 domain fact를 직접 소유하는 monolith가 아니다.

```text
Discord / Web / CLI / ChatGPT / schedules / watchers / external events
                              │
                              ▼
                         Edge / Ingress
                   local reply or escalation
                              │
                              ▼
                    All Tomorrow Authority
        ┌────────────────────────────────────────────┐
        │ project / Goal / Plan / Work / Trigger     │
        │ policy / budget / permission               │
        │ resource state / observations              │
        │ pipeline version / Run / Question          │
        │ project coordination state / provenance    │
        │ event / artifact / lesson / proposal meta  │
        └────────────────────────────────────────────┘
                              │
                              ▼
                      Planner / Replanner
         Goal + current state + policy + observations
                              │
                     Plan / Work revision
                              │
                              ▼
                     Execution Resolution
             capability → worker/agent → executor/host
                         → provider resource
                              │
                              ▼
                   Versioned Pipeline Recipe
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
          workers            tools          adapters
      coding/analysis     MCP/native       Eve/Manager/
                                           providers/etc.
             │                │                │
             └────────────────┼────────────────┘
                              ▼
              results / artifacts / observations
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
               state/events       Replanner input
```

중앙집권의 의미는 **하나의 authority에서 목표·작업·라우팅·추적·질문·결과를 조정할 수 있다**는 뜻이다. 모든 데이터를 한 DB로 옮긴다는 뜻이 아니다.

## 2. Core Layering

### 2.1 Ingress

사용자 메시지만 ingress가 아니다.

최종적으로 지원할 origin:

- user request
- schedule
- external event/webhook
- watcher condition
- system-generated proposal

현재 Discord edge policy와 Web API는 이 층의 초기 구현이다.

### 2.2 Goal, Plan and Work

장기 목적과 durable work는 pipeline보다 위에 둔다.

- **Goal**: 여러 plan, work, run에 걸쳐 살아남는 목적과 acceptance criteria
- **Plan**: 현재 state/policy/resource 조건에서 Goal을 달성하기 위한 versioned work graph
- **PlanRevision**: observation 때문에 기존 Plan을 유지·변경·축소·연기한 새 version과 rationale
- **WorkItem**: 실제 수행·추적·대기·재시도되는 durable 작업
- **Run**: WorkItem을 특정 pipeline version으로 실행한 한 시도

Goal과 Plan을 분리한다. resource 하나가 막혔다고 Goal을 폐기하거나 처음부터 다시 만들지 않는다. 완료된 Work/Artifact를 보존하면서 남은 work만 재계산할 수 있어야 한다.

하나의 WorkItem이 worker 교체, 재시도, NEED_USER, 여러 날의 대기를 거쳐도 Work identity를 잃지 않아야 한다.

현재 DB의 `tasks`는 이 목표 WorkItem/Plan 모델에 비해 얇으며 1차 완성에서 재검토한다.

### 2.3 Planner / Replanner

Planner가 장기적인 "어떻게 할 것인가"를 소유한다. Pipeline이 이 책임을 대신하지 않는다.

입력:

- Goal / acceptance criteria
- current Plan and Work state
- project coordination context
- capability/resource snapshot
- budget / permission / policy
- recent observations
- reusable artifact/lesson refs

출력:

- Plan or PlanRevision candidate
- create/keep/cancel/defer WorkItem decisions
- capability/resource constraints
- user input requirement
- rationale/provenance

Planner 출력은 곧바로 실행 권한이 아니다. durable Plan/Work로 materialize하기 전에 최소한 contract/schema, dependency consistency, referenced resource existence, permission/risk policy, hard budget, acceptance-criteria preservation, required user approval을 검증한다.

Planner 구현은 rule-based, LLM, hybrid 등으로 교체 가능해야 한다. 특정 모델 prompt나 특정 provider 이름이 architecture contract가 아니다.

Replanner는 quota, rate limit, resource health, cost, quality, deadline, user input 같은 현실 변화가 들어왔을 때 **계획 의미가 달라져야 하는 경우** Goal을 기준으로 남은 Plan을 다시 계산한다. policy에 따라 scope/quality degradation, concurrency reduction, defer, split, wait, NEED_USER 등을 선택할 수 있다.

같은 capability, quality floor, permission, budget 조건을 만족하는 동등 resource로의 단순 failover는 PlanRevision 없이 Execution Resolution이 처리할 수 있다. 모든 transient failure를 Planner로 끌어올려 불필요한 plan churn을 만들지 않는다.

Goal/acceptance criteria를 조용히 낮추는 것은 replanning이 아니다. 사용자 의도를 바꿀 정도의 축소는 명시된 policy가 없으면 NEED_USER로 간다.

### 2.4 Execution Resolution

Execution Resolution은 Planner가 요구한 **capability와 constraints**를 현재 registry/resource state의 구체 worker/tool/executor/provider resource에 늦게 매핑한다.

가능하면 Plan은 특정 provider 이름보다 필요한 capability/quality/privacy/budget/deadline constraints를 표현한다. concrete resource pinning이 정말 필요한 경우에만 명시적 resource ref를 둔다.

분리해서 다룬다.

- project
- capability
- worker/agent
- tool
- executor/host
- provider resource/account reference
- budget
- permission/risk
- pipeline recipe

초기 구현은 capability → CLI worker 선택만 수행한다. 이를 최종 형태로 오인하지 않는다.

Registry는 후보와 state를 제공하고, 장기 Plan 결정 자체를 소유하지 않는다. Execution Resolution은 동등 후보 failover를 담당할 수 있지만 Goal의 범위·품질·시간 구조를 바꾸지 않는다.

Selection/ranking strategy는 replaceable policy로 분리 가능해야 한다. 현재 코드의 quality/cost/latency 고정 sort는 초기 구현이며 architecture invariant가 아니다.

### 2.5 Project Context Assembly

중앙집권의 핵심 문제는 모든 채팅 로그를 한곳에 복제하는 것이 아니라, 새 client/worker가 프로젝트의 현재 상태를 다시 잃지 않게 하는 것이다.

중앙은 **cross-system coordination state**를 소유한다.

중앙-owned 예:

- current cross-system objective
- active orchestration constraints/invariants
- decision/source refs
- open Goal/Work
- relevant outcome/artifact/lesson refs

반대로 Git/Eve/Manager/Discord가 소유하는 domain fact는 중앙 coordination state의 새 canonical copy로 만들지 않는다. 필요하면 owner ref/version/freshness를 가진 projection/cache 또는 live adapter 조회로 가져온다.

실행 전 context assembler는 중앙-owned coordination state와 source-owned adapter 조회를 결합해 bounded context pack을 만든다.

Worker 실행 입력은 raw RequestEnvelope 자체가 아니라 WorkItem의 task/acceptance criteria/constraints와 선택된 context/artifact/source refs를 조립한 구조다. RequestEnvelope의 원문은 provenance와 사용자 의도를 보존하는 입력이지, 모든 downstream worker prompt의 전체 문맥을 대신하지 않는다.

context pack 자체는 근거 없는 새 정본이 아니며 provenance/source refs를 보존한다. size/cost budget을 적용하고 raw chat history를 거대한 handover 파일 하나로 대체하는 구조를 만들지 않는다.

### 2.6 Pipeline

Pipeline은 **하나의 WorkItem을 실행하는 versioned recipe**다.

현재 runtime이 유지하는 좋은 경계:

- YAML/JSON spec load
- immutable version identity
- node registry
- safe variable resolution
- sequential execution + limited branch
- retry metadata
- NEED_USER suspend/resume
- cancellation
- event emission

Pipeline 자체가 Goal manager, planner/replanner, scheduler, resource pool, long-term memory, self-improvement controller를 모두 먹지 않는다.

Pipeline YAML은 provider/project/failure 이름별 의사결정 표가 아니다. 특정 capability의 실행 recipe가 정말 달라질 때만 별도 pipeline을 만들고, quota/resource/user-input 같은 cross-cutting 판단은 Planner/Policy/Observation 계층에서 처리한다.

### 2.7 Execution

실행 capability와 실행 위치/자원을 분리한다.

- Worker/Agent: 무엇을 할 수 있는가
- Executor/Host: 어디서 어떻게 실행하는가
- Provider Resource: 어떤 model/provider/account/quota/credential ref를 쓰는가

현재 AntigravityWorker/OpenCodeWorker는 로컬 CLI worker+executor가 한 adapter 안에 붙어 있는 초기 구현으로 본다. 1차 완성에서 미래 분리를 막지 않는 contract seam을 만든다.

Provider-specific protocol, SDK, authentication, raw error parsing은 adapter/resource boundary에 가둔다. 예를 들어 서로 다른 provider의 quota error 문구는 adapter가 generic `capacity_exhausted` 계열 observation으로 정규화하고 원문 detail/ref를 함께 남길 수 있어야 한다. Planner가 provider raw error string을 직접 분기하지 않는다.

Project source identity와 executor-local workspace path도 분리한다. `repo:C:/projects/...` 같은 경로는 특정 host의 checkout 위치일 뿐 cross-system project identity가 아니다. logical repository/source ref를 executor가 자신의 workspace mapping으로 실제 cwd에 해석한다.

### 2.8 State, Observations, Events, Artifacts

- canonical projection과 append-only event를 분리한다.
- **Observation**은 Planner/Replanner가 현재 세계 상태 변화를 해석하기 위한 입력이다.
- Observation은 provider-specific detail을 보존하되 generic semantic category와 resource/work refs를 가져야 한다.
- ResourceState는 availability, capacity/quota, rate-limit, health, cost/quality class, reset/expiry 같은 현재 상태를 표현할 수 있다. 모든 provider가 정확한 quota telemetry를 제공한다고 가정하지 않고 known / unknown / estimated와 source, observed_at, freshness/confidence를 표현할 수 있어야 한다.
- Policy는 허용된 degradation/fallback/budget/approval boundary를 표현한다.
- event는 수정 이력이 아니라 provenance/history다.
- Artifact는 bytes 자체가 아니라 중앙에서 추적할 metadata identity를 가진다.
- 대용량 bytes는 source/object storage owner에 둘 수 있다.

### 2.9 Knowledge and Improvement

Lesson/Evaluation/Proposal은 중앙 orchestration 지식의 lifecycle이다.

```text
event/run/artifact
      ↓
lesson candidate
      ↓
evidence/reuse/evaluation
      ↓
accepted lesson or improvement proposal
      ↓
sandbox/evaluation
      ↓
promotion or rejection
```

현재 lesson/evaluation class는 초기 골격이다. 자동 promotion은 아직 구현된 것으로 보지 않는다.

## 3. Source Ownership

### 중앙이 소유하는 정본

- project registration identity와 중앙 source references
- Goal/WorkItem/Run의 orchestration state
- cross-system project coordination state와 source/decision refs
- versioned pipeline specifications/records
- execution event와 trace linkage
- pending user questions와 resume state
- worker/tool/executor/resource registry metadata
- trigger/schedule metadata
- artifact catalog metadata
- lesson/evaluation/improvement proposal metadata

### 중앙이 소유하지 않는 정본

- Eve persona/world/scene canonical state
- Manager persona와 Manager-owned personal facts
- 각 Git repository의 코드/Git history
- Discord 원본 메시지
- Notion에 이미 owner가 있는 domain facts
- provider secret 값
- 외부 서비스가 소유하는 원본 artifact bytes

동일 사실을 여러 저장소에 쓰는 adapter는 projection임을 명시하고 owner/version/provenance를 보존한다.

`Project.owner`와 domain canonical owner를 같은 의미로 쓰지 않는다. 현재 catalog의 `owner` 의미가 모호하므로 1차 완성에서 registry ownership과 source/canonical ownership을 구분한다.

## 4. Core Invariants

1. Original Vision이 파생 설계보다 우선한다.
2. Control Plane은 최종 목적을 위한 수단이다.
3. **Generality over case-by-case hardcoding** — 새 provider/tool/project/failure를 지원할 때 generic core/pipeline의 이름별 branch 추가를 기본 해법으로 삼지 않는다.
4. **Planner owns planning/replanning; Pipeline owns bounded execution recipe.**
5. **Goal is stable, Plan is revisable.** resource/state 변화는 Goal 폐기보다 PlanRevision의 입력이 된다.
6. Clients, models, planners, workers, executors, tools, providers, pipelines는 교체 가능하다.
7. 새 종류는 가능한 한 capability + metadata + adapter + resource state + policy로 시스템에 참여한다.
8. provider-specific protocol/error/auth 특수성은 adapter 경계에 가둔다.
9. Goal/Plan/Work history, accumulated knowledge, provenance, user control은 교체에서 살아남는다.
10. Central authority does not imply central execution or central ownership of domain facts.
11. No new knowledge island.
12. Ask rather than hallucinate ownership, target, permission or required input.
13. Preserve provenance.
14. Background work yields to interactive user work at safe boundaries.
15. Evaluation precedes production self-improvement promotion.

### Hardcoding Boundary

코드에 고정해도 되는 것과 환경/정책 데이터로 남겨야 하는 것을 구분한다.

**Stable primitives / invariants — code contract 가능**

- node/run status semantics: SUCCESS, FAILED, NEED_USER 등
- provenance/trace requirement
- permission and secret-handling boundary
- adapter interface
- Plan/Work/Event/Observation lifecycle invariants
- transactional/idempotency rules

**Changing domain decisions — generic core에 이름별 하드코딩 금지**

- provider/model/account/project 이름
- quota 숫자와 reset 정책
- worker/resource ranking 우선순위
- fallback/degradation 순서
- research site/URL
- "이 서비스면 이 pipeline" 같은 case table
- 특정 provider raw error string

범용성은 모든 것을 문자열 metadata로 바꾸는 것이 아니라 **변화 속도가 다른 책임을 올바른 층에 두는 것**이다.

## 5. Current Contracts

### RequestEnvelope

원문을 보존하면서 edge 분석은 hint로 전달한다.

```text
request_id
received_at
source
message
attachments
session_ref
edge_analysis
candidate_project_id
central_reason
```

RequestEnvelope는 ingress contract다. 장기 Work identity를 대신하지 않는다.

### ExecutionContext

현재 구현:

```text
request
user_ref
project_ref
session_ref
trace
memory_refs
artifact_refs
variables
budget
permissions
```

### NodeResult

```text
status: SUCCESS | FAILED | RETRY | WAITING | NEED_USER | CANCELLED
output
artifacts
events
next_hint
user_question
error
```

`NEED_USER`는 저장된 run/step과 연결된 resume token을 사용한다.

### PipelineSpec

```text
pipeline_id
version
status
parent_version
change_reason
trigger
steps
```

Pipeline spec의 `trigger` metadata와 장기 Trigger entity는 역할을 구분한다. Pipeline trigger는 "이 recipe가 어떤 intent/event에 적합한가"를 표현할 수 있고, durable Trigger는 미래 시점/조건에서 WorkItem을 발생시키는 authority다.

### Event

```text
event_id
occurred_at
user_id
project_id
session_id
trace_id
run_id
actor
type
parent_event_id
input_ref
output_ref
artifact_refs
metadata
```

Event는 append-only다.

### Target Planning Contracts — 1차에서 추가할 경계

아래는 아직 현재 구현 contract로 간주하지 않는다. 1차 Gate A의 목표 계약이다.

#### Plan / PlanRevision

```text
plan_id
version
goal_id
status
work_refs / dependency refs
assumption refs
policy_ref
resource_snapshot_ref
rationale
created_from_observation_refs
supersedes_version
created_at
```

#### Observation

```text
observation_id
type / semantic category
occurred_at
source_ref
project_id / goal_id / work_id / run_id
resource_ref
severity
details_ref / metadata
```

#### ResourceState

```text
resource_id
capabilities
availability
capacity/quota state: known | unknown | estimated + value/ref
rate-limit state
health
cost class
quality/evaluation refs
credential_ref
source_ref
observed_at / freshness / confidence
```

#### ResourceCandidate

새 resource/tool/provider를 바로 production registry에 넣지 않고 candidate lifecycle을 거칠 수 있어야 한다.

```text
candidate_id
source/provenance refs
claimed capabilities
public quota/pricing/terms metadata
prerequisites / required_user_action
expected utility
duplication/risk assessment
status: discovered | watch | needs_user | experimenting | evaluated | available | rejected
evaluation refs
```

credential 자체는 candidate metadata에 저장하지 않는다.

#### PolicyRef

Policy 내용은 versioned data로 관리할 수 있으며 Plan과 Work가 어떤 정책 하에서 만들어졌는지 참조 가능해야 한다.

예:

```text
budget / free-only constraint
quality floor
deadline / priority
privacy / risk
fallback/degradation permission
user approval requirements
```

이 계약의 목적은 세상의 모든 provider 필드를 사전에 하나의 거대한 schema로 통일하는 것이 아니다. Planner가 공통 의미를 읽을 수 있는 최소 semantic layer와 provider-specific detail ref를 분리하는 것이다.

## 6. Edge Escalation

Edge는 local 처리와 중앙 escalation을 구분한다.

현재 Discord signal:

```text
needs_shared_memory
needs_project_state
needs_cross_project_knowledge
needs_remote_tool
needs_long_running_task
needs_canonical_mutation
```

모두 false인 일반 대화는 중앙 Work/Run 생성을 강제하지 않는다.

하나 이상 true여도 edge가 최종 authority가 되지 않는다. 중앙이 project, ownership, risk, permission을 다시 검증한다.

## 7. Persistence and Scheduling

### PostgreSQL

1차 기본 durable authority로 PostgreSQL을 우선한다.

현재 migration에는 projects/tasks/runs/run_steps/events/pipeline_versions/user_questions/registry 구조와 lessons 구조가 있다.

1차 완성에서 추가/보강할 논리 영역:

```text
goals
plans / plan_revisions
work_items or expanded tasks
work_dependencies
observations
policy versions / refs
resource state snapshots
triggers
artifacts
executors
provider_resources
leases / scheduling state
```

정확한 테이블 이름은 구현 시 schema review에서 결정한다.

### Scheduler

현재 `WorkQueue`는 in-memory prototype이다.

최종 scheduler에는 최소한 다음 경계가 필요하다.

- durable enqueue
- not-before time
- priority
- atomic claim
- lease/heartbeat or equivalent recovery
- retry/requeue
- cancellation
- crash recovery

Redis는 요구가 증명되기 전 필수가 아니다.

## 8. Remote Operation

"어느 기기에서든 접속"은 architecture requirement다.

1차 목표는 복잡한 분산 시스템이 아니라:

- remotely reachable authenticated Web surface
- HTTPS
- persistent DB
- restart recovery
- secrets separation
- health checks
- minimal backup/restore

배포 provider는 교체 가능하게 두며 현재 사용 가능한 AWS 자원은 첫 배포 후보일 뿐 contract 자체는 아니다.

## 9. Security and Mutation

- credential 값은 contract/event/log/artifact metadata에 기록하지 않는다.
- adapter/executor는 opaque credential/resource reference만 받는다.
- Planner가 만든 Plan/PlanRevision candidate는 schema/policy/permission/budget validation 없이 실행하지 않는다.
- canonical write와 high-risk tool은 중앙 policy 확인이 필요하다.
- mutation target이 모호하면 NEED_USER.
- 외부 mutation은 idempotency key와 trace를 가진다.
- provider/account 자동화는 실제 허용 범위와 정책을 따른다.
- 새 credential/user action 요청은 candidate utility/risk/user-effort gate를 통과한 경우에만 생성한다.
- 외부 웹/문서/repository 내용은 untrusted evidence로 처리하며 그 안의 지시문을 system/policy authority로 승격하지 않는다.
- research 단계에서 외부 repository script/code를 임의 실행하지 않는다. 실행이 필요하면 sandbox/evaluation work로 별도 승격한다.
- self-improvement proposal은 평가 없이 production을 직접 수정하지 않는다.

## 10. Current Implementation Boundary

2026-09-19 현재 구현된 중심부:

- Request/Execution/Node/Pipeline/Event contracts
- sequential versioned pipeline runtime
- NEED_USER resume
- in-memory + PostgreSQL run/question store 구현
- initial migrations
- CapabilityRegistry / WorkerService
- 현재 worker selection의 고정 quality/cost/latency sort와 tool latency sort
- Antigravity/OpenCode CLI adapters
- Discord edge policy와 shadow routing experiment
- minimal authenticated Web UI/API
- initial scheduler/lesson/evaluation objects

아직 목표 구조로 간주하지 않는 것:

- Goal/Plan/Work graph
- Planner/Replanner contract와 durable PlanRevision
- normalized Observation/ResourceState/Policy lifecycle
- replaceable selection/ranking policy
- durable trigger engine
- production scheduler leases
- executor/provider resource pool
- end-to-end remote production deployment
- store-backed Web execution path
- automatic lesson/evaluation loop
- autonomous watchers/experiments
- self-improvement promotion/rollback

세부 구현 순서는 [roadmap.md](roadmap.md)와 각 completion-stage 문서를 따른다.
