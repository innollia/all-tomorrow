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
        ┌──────────────────────────────────────────┐
        │ project / goal / work / trigger          │
        │ permission / budget / orchestration      │
        │ pipeline version / run / question        │
        │ project context projection / provenance │
        │ event / artifact metadata                │
        │ lesson / evaluation / proposal metadata  │
        └──────────────────────────────────────────┘
                              │
                              ▼
                     Execution Resolution
            capability → worker/agent → executor/host
                         → provider resource
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
          workers            tools          adapters
      coding/analysis     MCP/native       Eve/Manager/
                                           Discord/etc.
             │                │                │
             └────────────────┼────────────────┘
                              ▼
                    source-owned systems
              Git / Notion / Discord / DB /
                object storage / providers
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

### 2.2 Goal and Work

장기 목적과 durable work는 pipeline보다 위에 둔다.

- Goal: 여러 work와 여러 run에 걸쳐 살아남는 목적
- WorkItem: 실제 수행·추적·대기·재시도되는 durable 작업
- Run: WorkItem을 특정 pipeline version으로 실행한 한 시도

하나의 WorkItem이 worker 교체, 재시도, NEED_USER, 여러 날의 대기를 거쳐도 Work identity를 잃지 않아야 한다.

현재 DB의 `tasks`는 이 목표 WorkItem 모델에 비해 얇으며 1차 완성에서 재검토한다.

### 2.3 Orchestration

오케스트레이션은 다음을 분리해 판단할 수 있어야 한다.

- project
- capability
- worker/agent
- tool
- executor/host
- provider resource/account reference
- budget
- permission/risk
- pipeline

초기 구현은 capability → CLI worker 선택만 수행한다. 이를 최종 형태로 오인하지 않는다.

### 2.4 Project Context Assembly

중앙집권의 핵심 문제는 모든 채팅 로그를 한곳에 복제하는 것이 아니라, 새 client/worker가 프로젝트의 현재 상태를 다시 잃지 않게 하는 것이다.

중앙은 cross-system coordination projection을 유지할 수 있다.

예:

- current objective
- active constraints
- decision/source refs
- open Goal/Work
- relevant outcome/artifact/lesson refs

실행 전 context assembler는 이 projection과 source-owned adapter 조회를 결합해 bounded context pack을 만든다.

Worker 실행 입력은 raw RequestEnvelope 자체가 아니라 WorkItem의 task/acceptance criteria/constraints와 선택된 context/artifact/source refs를 조립한 구조다. RequestEnvelope의 원문은 provenance와 사용자 의도를 보존하는 입력이지, 모든 downstream worker prompt의 전체 문맥을 대신하지 않는다.

context pack 자체는 근거 없는 새 정본이 아니며 provenance/source refs를 보존한다. size/cost budget을 적용하고 raw chat history를 거대한 handover 파일 하나로 대체하는 구조를 만들지 않는다.

### 2.5 Pipeline

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

Pipeline 자체가 Goal manager, scheduler, resource pool, long-term memory, self-improvement controller를 모두 먹지 않는다.

### 2.6 Execution

실행 capability와 실행 위치/자원을 분리한다.

- Worker/Agent: 무엇을 할 수 있는가
- Executor/Host: 어디서 어떻게 실행하는가
- Provider Resource: 어떤 model/provider/account/quota/credential ref를 쓰는가

현재 AntigravityWorker/OpenCodeWorker는 로컬 CLI worker+executor가 한 adapter 안에 붙어 있는 초기 구현으로 본다. 1차 완성에서 미래 분리를 막지 않는 contract seam을 만든다.

Project source identity와 executor-local workspace path도 분리한다. `repo:C:/projects/...` 같은 경로는 특정 host의 checkout 위치일 뿐 cross-system project identity가 아니다. logical repository/source ref를 executor가 자신의 workspace mapping으로 실제 cwd에 해석한다.

### 2.7 State, Events, Artifacts

- canonical projection과 append-only event를 분리한다.
- event는 수정 이력이 아니라 provenance/history다.
- Artifact는 bytes 자체가 아니라 중앙에서 추적할 metadata identity를 가진다.
- 대용량 bytes는 source/object storage owner에 둘 수 있다.

### 2.8 Knowledge and Improvement

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
- cross-system project coordination projection과 source/decision refs
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
3. Clients, models, workers, executors, tools, providers, pipelines는 교체 가능하다.
4. Goal/Work history, accumulated knowledge, provenance, user control은 교체에서 살아남는다.
5. Central authority does not imply central execution or central ownership of domain facts.
6. No new knowledge island.
7. Ask rather than hallucinate ownership, target, permission or required input.
8. Preserve provenance.
9. Background work yields to interactive user work at safe boundaries.
10. Evaluation precedes production self-improvement promotion.

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
work_items or expanded tasks
work_dependencies
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
- canonical write와 high-risk tool은 중앙 policy 확인이 필요하다.
- mutation target이 모호하면 NEED_USER.
- 외부 mutation은 idempotency key와 trace를 가진다.
- provider/account 자동화는 실제 허용 범위와 정책을 따른다.
- self-improvement proposal은 평가 없이 production을 직접 수정하지 않는다.

## 10. Current Implementation Boundary

2026-09-19 현재 구현된 중심부:

- Request/Execution/Node/Pipeline/Event contracts
- sequential versioned pipeline runtime
- NEED_USER resume
- in-memory + PostgreSQL run/question store 구현
- initial migrations
- CapabilityRegistry / WorkerService
- Antigravity/OpenCode CLI adapters
- Discord edge policy와 shadow routing experiment
- minimal authenticated Web UI/API
- initial scheduler/lesson/evaluation objects

아직 목표 구조로 간주하지 않는 것:

- Goal/Work graph
- durable trigger engine
- production scheduler leases
- executor/provider resource pool
- end-to-end remote production deployment
- store-backed Web execution path
- automatic lesson/evaluation loop
- autonomous watchers/experiments
- self-improvement promotion/rollback

세부 구현 순서는 [roadmap.md](roadmap.md)와 각 completion-stage 문서를 따른다.
