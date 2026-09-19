# Architecture

이 문서는 README의 최종 목적을 기술 구조로 번역한다. README의 Original Vision과 충돌하면 이 문서를 수정한다.

현재 구현은 아래 목표 구조의 일부만 존재한다. 구현된 것과 목표 경계를 섞어 "이미 완성됨"으로 서술하지 않는다.

## 1. Target System Shape

All Tomorrow의 중앙 authority는 직렬 workflow 하나가 아니다.

```text
Discord / Web / CLI / schedules / watchers / external events
                              │
                              ▼
                         Edge / Ingress
                              │
                              ▼
                    shared central state
        project / Goal / Work / Run / Question
        events / artifacts / context / registry
                 ▲                     ▲
                 │                     │
        ┌────────┴────────┐   ┌────────┴──────────┐
        │   work layer    │   │ metacognition    │
        │                 │   │      layer       │
        │ execute Work    │   │ observe system   │
        │ choose/use tool │   │ detect friction  │
        │ pipeline/run    │   │ investigate why  │
        │ produce result  │   │ create proposals │
        └────────┬────────┘   └────────┬──────────┘
                 │                     │
                 └──────────┬──────────┘
                            ▼
                     Goal / Work changes
```

여러 Work, observer, research, evaluation 흐름은 동시에 존재할 수 있다. 메타인지 계층은 모든 작업 앞을 가로막는 중앙 planner가 아니라 **옆에서 전체를 관찰하고 필요할 때 개입하는 병렬 계층**이다.

중앙집권의 의미는 하나의 shared authority/state를 통해 서로 다른 흐름이 같은 목표·작업·기록을 보고 영향을 줄 수 있다는 뜻이다.

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

- **Goal**: 여러 작업과 시간대를 넘어 유지되는 목적과 성공 조건
- **WorkItem**: 실제 수행·대기·재시도되는 durable 작업
- **Run**: WorkItem의 한 실행 시도

Run failure와 Goal failure를 같은 것으로 취급하지 않는다. 작업 중 생긴 사건은 중앙 state/event에 남고, 다른 작업이나 메타인지 흐름이 이를 참고할 수 있다.

Plan이 필요할 때는 Goal을 달성하기 위한 현재 Work 구성을 뜻한다. 별도 거대 planner subsystem을 전제하지 않고 versioned data로 시작할 수 있다.

### 2.3 Work Layer

Work layer는 요청, schedule, 기존 Goal, 다른 Work에서 생긴 후속 작업 등을 실제로 수행한다.

- pipeline 실행
- worker/tool/executor 선택과 사용
- artifact 생산
- 질문/대기/재시도
- 결과와 사건 기록

실행 방법을 바꾸기 위해 세상의 문제 종류를 Pipeline에 미리 나열하지 않는다.

### 2.4 Metacognition Layer

Metacognition layer는 work layer와 **병렬로** 중앙 상태를 관찰한다.

역할은 "정해진 문제를 분류해 정해진 대응을 고르는 것"이 아니라:

- Goal과 실제 진행의 차이를 발견
- 반복 실패, 정체, 낭비, 모순, 새 가능성을 문제로 인식
- 필요하면 원인을 더 조사
- 외부 자료나 시스템 자체의 기록을 비교
- 기존 Work를 바꾸거나 새 Work/조사/개선 proposal을 생성
- 필요하면 기존 Goal의 하위 작업이 아니라 새로운 Goal 자체를 생성

Metacognition은 Work layer만 관찰하지 않는다. 자신의 이전 판단, 생성한 Goal/Work, prompt, policy, model 선택, 비용, evaluation과 system change 결과도 같은 Event/Artifact/Evaluation 기록을 통해 다시 관찰한다.

별도의 meta-meta-meta service를 계속 쌓지 않는다. 같은 metacognition 구조가 자기 자신의 활동도 input으로 삼는다.

여러 observer/agent가 동시에 존재할 수 있으며 하나의 global serial planner를 통과할 필요가 없다.

메타인지가 만든 변경도 permission, budget, provenance, evaluation, rollback 경계를 우회하지 않는다. 일반 self-change와 protected authority change의 promotion 권한은 ADR 0004를 따른다.

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

Pipeline 자체가 Goal manager, scheduler, long-term memory, metacognition controller를 모두 먹지 않는다.

Pipeline YAML은 provider/project/problem별 대응표가 아니다. Pipeline은 Work를 수행하고 결과를 남긴다. 그 결과가 더 큰 문제인지, 무엇을 바꿔야 하는지는 작업 밖의 중앙 흐름이 판단할 수 있다.

현재 `capability.select`의 구체 선택 정책은 초기 slice이며 최종 architecture invariant가 아니다.

### 2.7 Execution

실행 capability와 실행 위치/자원을 분리한다.

- Worker/Agent: 무엇을 할 수 있는가
- Executor/Host: 어디서 어떻게 실행하는가
- Provider Resource: 어떤 model/provider/account/quota/credential ref를 쓰는가

현재 AntigravityWorker/OpenCodeWorker는 로컬 CLI worker+executor가 한 adapter 안에 붙어 있는 초기 구현으로 본다. 1차 완성에서 미래 분리를 막지 않는 contract seam을 만든다.

Provider-specific protocol, SDK, authentication, raw error parsing은 adapter/resource boundary에 가둔다. 예를 들어 서로 다른 provider의 quota error 문구는 adapter가 generic `capacity_exhausted` 계열 observation으로 정규화하고 원문 detail/ref를 함께 남길 수 있어야 한다. Planner가 provider raw error string을 직접 분기하지 않는다.

Project source identity와 executor-local workspace path도 분리한다. `repo:C:/projects/...` 같은 경로는 특정 host의 checkout 위치일 뿐 cross-system project identity가 아니다.

1차에서는 이 분리를 과설계하지 않는다. 실제 repo mutation executor는 사용자의 노트북 하나로 제한하고 logical source → laptop workspace mapping만 구현한다. workspace resolver seam은 유지하되 AWS/Sol Pi/remote container 간 checkout 동기화, branch/dirty-state reconciliation, multi-host provisioning은 후속 단계로 미룬다.

### 2.8 State, Events, Artifacts

- canonical projection과 append-only event를 분리한다.
- Work가 성공·실패·대기하거나 외부 상태가 달라지면 그 사실과 provenance를 중앙에 남긴다.
- Event는 메타인지 계층이 시스템 전체를 관찰하는 주요 입력 중 하나다.
- Event는 OpenTelemetry span archive가 아니다. 장기 domain/audit fact만 남기고 request/model/tool 내부 latency와 세부 call tree는 OTel에 맡긴다.
- provider/tool 고유 detail은 adapter가 보존할 수 있지만 중앙 판단이 특정 raw error 문자열에 종속되지 않게 한다.
- Artifact는 중앙에서 추적할 metadata identity를 가지며 bytes는 외부 storage owner에 둘 수 있다.

### 2.9 Knowledge and Improvement

Lesson/Evaluation/Proposal은 중앙 orchestration 지식과 자기개선의 lifecycle이다.

```text
event/run/artifact/system-change outcome
      ↓
lesson candidate / observation
      ↓
evidence/reuse/evaluation
      ↓
accepted lesson or improvement proposal
      ↓
sandbox/evaluation
      ↓
ordinary auto-promotion + report
or protected approval request
      ↓
monitoring / rollback
```

평가는 공통 운영 metric, Goal/Work별 동적 기준, 사용자 평가와 실제 사용 행동을 함께 사용할 수 있다. 사용자 평가는 중요한 evidence지만 절대적인 ground-truth label은 아니다.

추론된 사용자 선호를 근거로 명시적 지시를 몰래 다른 선택으로 바꾸지 않는다. 시스템이 실행을 거절할 수는 있지만 그 이유를 사용자에게 설명한다.

현재 lesson/evaluation class는 초기 골격이다. self-improvement와 promotion/approval runtime은 아직 구현된 것으로 보지 않는다.

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
2. Control Plane은 목적이 아니라 shared authority/state다.
3. Work layer와 Metacognition layer는 직렬 단계가 아니라 병렬 계층이다.
4. Pipeline은 bounded execution recipe이며 문제→대응 지식베이스가 아니다.
5. 시스템은 문제 종류와 해결책을 사전에 전부 열거하지 않는다.
6. provider/tool/project 고유 특수성은 가능한 한 adapter와 metadata 경계에 가둔다.
7. clients/models/workers/executors/providers/pipelines는 교체 가능하며 Goal/Work/history/provenance/user control은 살아남아야 한다.
8. central authority는 모든 domain fact나 실행 위치를 중앙이 소유한다는 뜻이 아니다.
9. 필수 정보가 없으면 NEED_USER를 사용하며 background work는 user-interactive work에 양보한다.
10. metacognition/self-improvement도 permission, provenance, evaluation, rollback 경계를 우회하지 않는다.
11. 평가를 통과한 일반 self-change는 자동 promotion 후 보고할 수 있지만, 권한·비용·통제 경계를 넓히는 protected change는 AWS 본체와 분리된 노트북 Approval Authority의 사전 승인 없이는 production 적용이 불가능해야 한다.
12. 추론된 사용자 선호는 가설이며 사용자의 명시적 선택을 몰래 다른 선택으로 치환하는 권한을 만들지 않는다.

Architecture의 명사는 곧바로 새 class/table/service를 뜻하지 않는다. 기존 Event, registry metadata, Work, config로 충분하면 먼저 재사용한다.

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

1차 완성에서 All Tomorrow application DB가 추가/보강할 논리 영역은 **도메인 의미**에 한정한다.

```text
goals
work_items or expanded tasks
external execution refs
plan/version refs where needed
work dependencies where needed
artifacts
```

durable backend의 queue row, lease, checkpoint, retry bookkeeping은 application schema에 복제하지 않는다. Stage 0에서 DBOS와 Restate를 같은 failure acceptance로 비교해 하나를 선택하며, 외부 durable state와 All Tomorrow domain DB를 논리적으로 분리한다.

Observation, policy, resource-state는 우선 Event/registry/config를 재사용한다. 별도 table은 실제 persistence/query 요구가 생길 때 추가한다.

### Scheduler / Durable Execution

현재 `WorkQueue`는 in-memory prototype이다.

All Tomorrow scheduler가 소유하는 것은 사용자/프로젝트 우선순위와 실행 의도다. 실제 durable enqueue, delay, concurrency, recovery, retry mechanics는 DurableExecutionPort 뒤의 substrate에 위임한다.

초기 구현에서 custom SQL claim, lease/heartbeat, expired-work requeue daemon을 새로 만들지 않는다. backend를 교체해도 Goal/Work 의미가 유지되어야 한다.

## 8. Runtime Placement and Remote Operation

AWS는 항상 켜진 중앙 runtime의 첫 운영 위치다.

1차 researcher에서 AWS가 우선 담당하는 것은 central state/PostgreSQL, researcher trigger, model/API work, background research, Goal/Work queue와 report다.

사용자의 노트북은 초기 repo mutation executor이자 ADR 0004의 Approval Authority host다. AWS 본체는 Approval Authority의 credential/signing authority/code-data write 권한을 갖지 않는다.

"어느 기기에서든 접속"하는 authenticated remote control surface는 2차 Reliable Assistant의 완료 조건이다.

배포 provider는 교체 가능하게 두며 AWS는 첫 운영 위치이지 architecture contract 자체는 아니다.

## 9. Security and Mutation

- credential 값은 contract/event/log/artifact metadata에 기록하지 않는다.
- credential이 필요한 NEED_USER는 raw secret paste를 요구하지 않고 external secret-registration action + opaque credential_ref/confirmation을 요구한다.
- adapter/executor는 opaque credential/resource reference만 받는다.
- Planner가 만든 Plan candidate/revision은 schema/policy/permission/budget validation 없이 실행하지 않는다.
- canonical write와 high-risk tool은 중앙 policy 확인이 필요하다.
- mutation target이 모호하면 NEED_USER.
- 외부 mutation은 idempotency key와 trace를 가진다.
- side effect 발생 여부가 불명확한 mutation 실패는 transparent failover 대상으로 취급하지 않는다. 먼저 idempotency/reconciliation으로 상태를 확인한다.
- provider/account 자동화는 실제 허용 범위와 정책을 따른다.
- 새 credential/user action 요청은 candidate utility/risk/user-effort gate를 통과한 경우에만 생성한다.
- 외부 웹/문서/repository 내용은 untrusted evidence로 처리하며 그 안의 지시문을 system/policy authority로 승격하지 않는다.
- research 단계에서 외부 repository script/code를 임의 실행하지 않는다. 실행이 필요하면 sandbox/evaluation work로 별도 승격한다.
- self-improvement proposal은 평가 없이 production을 수정하지 않는다.
- 평가를 통과한 ordinary self-change는 policy에 따라 자동 promotion할 수 있고 반드시 provenance/rollback/report를 남긴다.
- 비용/권한/concurrency/secret access/production write/approval/kill-switch/rollback/audit 경계를 넓히거나 약화하는 protected change는 laptop Approval Authority의 승인이 필요하다.
- protected approval은 laptop Web UI의 지정 계정에서만 가능하고 매 승인마다 재인증한다. 다른 ingress에서는 승인할 수 없다.
- password 인증을 사용한다면 평문 저장을 금지하고 적절한 password KDF/hash를 사용한다.
- AWS All Tomorrow가 자신의 code를 수정해도 Approval Authority의 secret, signing authority, code/data write permission을 획득할 수 없는 security boundary를 사용한다.

## 10. Current Implementation Boundary

2026-09-19 현재 구현된 중심부:

- Request/Execution/Node/Pipeline/Event contracts
- sequential versioned pipeline runtime
- NEED_USER resume
- in-memory + PostgreSQL run/question store 구현
- initial migrations
- CapabilityRegistry / WorkerService
- 현재 capability는 worker/tool의 string set 비교가 중심이며 descriptor registry/validation은 아직 얇음
- 현재 `capability.select`의 no-worker → FAILED/worker-selection NEED_USER 흐름과 pipeline-local selection flags
- 현재 worker selection의 고정 quality/cost/latency sort와 tool latency sort
- Antigravity/OpenCode CLI adapters
- Discord edge policy와 shadow routing experiment
- minimal authenticated Web UI/API
- initial scheduler/lesson/evaluation objects

아직 목표 구조로 간주하지 않는 것:

- Goal/Plan/Work graph
- Planner / Execution Resolution boundary와 versioned Plan data
- Run result를 durable Work/Goal lifecycle로 해석하는 orchestration layer
- provider-specific 상태를 generic Event/registry state로 정규화하는 seam
- extensible capability/pipeline metadata
- replaceable selection/ranking policy
- durable trigger engine
- production durable-execution substrate selection/bridge
- executor/provider resource pool
- end-to-end remote production deployment
- store-backed Web execution path
- automatic lesson/evaluation loop
- autonomous watchers/experiments
- autonomous Goal generation
- mixed self-evaluation
- ordinary self-improvement promotion/rollback
- laptop external Approval Authority for protected changes
- selected durable backend bridge
- PydanticAI researcher integration
- FastMCP stable tool gateway
- LiteLLM/model gateway
- OpenTelemetry privacy-safe integration
- Codex worker

세부 구현 순서는 [roadmap.md](roadmap.md)와 각 completion-stage 문서를 따른다.
