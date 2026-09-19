# 1차 완성 — Durable Central Core

> Status: **In progress.** 현재 구현은 이 단계의 초기 실행 엔진이며, 다음 구조 작업은 Gate A다.


## Definition of Done

1차 완성은 "pipeline 몇 개가 실행된다"가 아니다.

사용자가 어느 기기에서든 중앙에 들어와 요청을 보내면, 그 요청이 적절한 Goal과 durable Work에 연결되고, **generic planner가 현재 context·policy·resource state를 보고 Plan/Work를 구성**하며, 필요한 pipeline/worker/tool로 실행되어야 한다. 실행 중 조건이 바뀌면 Goal을 잃지 않고 Plan을 revision할 수 있고, 사용자 정보가 필요하면 즉시 멈추고 질문하며, 서버 재시작 뒤에도 같은 work/run을 재개하고 결과·산출물·provenance를 다시 확인할 수 있어야 한다.

1차가 끝나면 시스템은 아직 자율 연구원이나 자기개선 시스템은 아니지만, 이후 2차·3차 기능이 core 재작성 없이 올라갈 수 있는 중앙 기반이어야 한다.

## Immediate Next Work

이 문서 개편 직후에는 Web 기능 추가나 watcher 구현으로 가지 않는다.

Gate A에서는 새 추상화를 많이 만드는 게 아니라 **현재 구조에서 책임이 잘못 놓인 부분만 최소 이동**한다.

1. 현재 `tasks/runs/events/CapabilityRegistry/capability.select/coding.yaml`에서 장기 planning, resource selection, retry 책임이 어디에 섞여 있는지 확인한다.
2. Goal과 Work의 durable identity를 먼저 잡고, Plan은 우선 **versioned data**로 표현한다. `PlanRevision` 전용 class/table은 필요가 증명되기 전 만들지 않는다.
3. quota/rate-limit/resource-unavailable 같은 변화는 우선 기존 Event/metadata를 활용해 generic observation으로 표현하고, 별도 observation table은 조회·수명주기 요구가 생길 때만 추가한다.
4. worker selection의 고정 정렬과 pipeline-local selection policy를 replaceable policy/execution-resolution 경계로 옮긴다.
5. 위 변경으로 필요한 최소 migration/test만 추가한 뒤 Gate B의 durable execution 검증으로 넘어간다.

**Gate A의 성공 기준은 타입 수가 늘어나는 것이 아니라, 새 provider/resource 상황을 기존 pipeline에 이름별 조건문 없이 처리할 수 있는 seam이 생기는 것**이다.

## 0. Preserve Existing Good Work

다음은 재작성 대상이 아니라 유지·확장 대상이다.

- RequestEnvelope / ExecutionContext / NodeResult
- immutable PipelineSpec version
- NEED_USER + resume
- append-only Event / trace
- source-owner-aware adapter boundary
- CapabilityRegistry와 worker selection의 provider-independent 방향
- Discord local-vs-central edge policy
- credential value를 중앙 로그에서 배제하는 원칙
- Evaluation이 직접 production mutation을 하지 않는 경계

다만 아래는 **현재 slice의 임시 책임 배치**로 보고 그대로 확대하지 않는다.

- `capability.select`가 pipeline 안에서 concrete worker 선택을 직접 소유
- no-worker 상황을 곧바로 pipeline FAILED로 끝내는 흐름
- `allow_policy_relaxation`, `require_user_selection` 같은 cross-cutting selection policy가 pipeline config에 있음
- `retry_on_fail` 같은 step retry와 resource-level retry/replan 의미가 아직 분리되지 않음

이 코드를 전부 버린다는 뜻은 아니다. selection primitive는 Execution Resolution service로 재사용하고, policy와 durable Work lifecycle을 위층으로 이동한다.

## 1. Architecture Correction Before More Surface Area

Web 기능과 application 등록을 크게 늘리기 전에 아래 모델을 먼저 확정한다.

### 1.1 Goal

장기 목표를 표현하는 durable entity.

최소 의미:

- goal id
- project scope 또는 personal scope
- title / intent
- status
- success criteria
- provenance / created_by
- optional parent goal

Goal은 pipeline run이 아니다. 하나의 Goal은 여러 WorkItem과 여러 run을 낳을 수 있다.

장기 프로젝트의 dependency graph는 WorkItem 관계로 표현한다. 이 요구 때문에 현재 Pipeline runtime을 곧바로 범용 DAG/orchestration engine으로 재작성하지 않는다. Pipeline 내부 DAG가 실제 recipe 요구로 별도 증명되기 전에는 sequential/limited-branch runtime을 유지할 수 있다.

### 1.2 WorkItem

실제 수행해야 하는 durable 단위.

최소 의미:

- work id
- optional goal id
- project id
- origin: user / schedule / watcher / event / system proposal
- status
- priority
- task description
- acceptance criteria
- dependencies
- not-before / deadline where applicable
- budget/policy refs
- current blocking reason
- resulting artifact/event refs

기존 `tasks` 모델은 이 요구를 수용할 수 있도록 재검토한다. 이름을 반드시 바꿀 필요는 없지만 단순 `title/status/priority` 행으로 끝내지 않는다.

### 1.3 Run

Run은 하나의 WorkItem을 특정 pipeline version으로 실행한 시도다.

- 같은 WorkItem에 여러 run이 붙을 수 있다.
- retry, resume, worker 교체 때문에 run history가 생겨도 WorkItem identity는 유지한다.
- 하나의 Run이 FAILED여도 WorkItem/Goal이 자동 terminal이 되지 않는다.
- resource unavailable/quota/capacity 같은 recoverable 원인이면 Observation을 남기고 Work를 replan/fallback/wait 대상으로 돌릴 수 있다.
- 사용자 질문은 run을 멈출 수 있지만 상위 WorkItem의 목적을 잃지 않는다.

### 1.4 Trigger

사용자 메시지만 ingress로 간주하지 않는다.

최소 origin model:

- user request
- schedule
- external event
- watcher condition
- system-generated proposal

1차에서는 모든 trigger type을 실제 구현할 필요가 없다. 다만 2차에서 schema를 갈아엎지 않도록 contract와 ownership을 먼저 잡는다.

### 1.5 Correlation Identity

Work identity와 execution trace를 같은 것으로 쓰지 않는다.

- `work_id`: 여러 실행 시도와 시간을 가로질러 유지되는 작업 identity
- `run_id`: 특정 pipeline execution attempt
- `trace_id`: 한 실행 흐름의 distributed trace
- 필요 시 parent/causation reference로 여러 run과 child work를 연결

현재 `runs.trace_id UNIQUE` 제약은 "trace 하나 = run 하나"에 가깝다. 이것을 Work identity 대신 사용하지 않는다. multi-run Work를 구현할 때 correlation 규칙과 schema를 먼저 확정한다.

### 1.6 Project Coordination Context

원문의 "전체 과정을 본 사용자와 handover 문서만 가진 worker 사이의 격차"를 직접 해결하는 층이다.

중앙은 raw chat 전체를 새 정본으로 복제하는 대신, **중앙이 실제로 소유해야 하는 cross-system coordination state**와 외부 owner를 가리키는 provenance/source reference를 유지한다. 외부 domain fact를 캐시해야 한다면 owner/version/freshness가 있는 projection으로 취급한다.

최소 포함 후보:

- current project objective
- active constraints/invariants
- current architecture/decision refs
- open Goals/WorkItems
- important source refs
- recent relevant outcomes
- accepted/relevant lesson refs
- unresolved questions/risks

실행 시에는 Request 하나만 worker에 던지지 않고 **bounded context pack**을 조립한다. context pack은 중앙 projection + source-owner adapter 조회 + 관련 lesson/artifact refs에서 만들며, 어떤 근거를 사용했는지 추적 가능해야 한다.

Worker 실행 입력은 최소한 다음을 구분할 수 있어야 한다.

- original request/message ref
- WorkItem task
- acceptance criteria
- active constraints
- project/source/workspace refs
- selected context pack / evidence refs
- artifact inputs
- permission/budget
- expected result form

현재 `pipelines/coding.yaml`의 `task: ${request.message}`는 초기 slice로 유지할 수 있지만 최종 execution input contract로 보지 않는다. 이미 Worker adapter가 지원하는 constraints/acceptance criteria를 Work/Context 층에서 실제로 공급하도록 연결한다.

context pack에는 크기/비용 budget을 두고, 모든 history를 통째로 prompt에 넣는 방식으로 handover 문제를 덮지 않는다.

Project context는 Git 코드, Eve state, Manager personal facts의 복제 정본이 아니다. 그 값들이 필요하면 source reference를 통해 읽는다.

### 1.7 Plan

Goal과 Plan을 같은 것으로 취급하지 않는다.

- **Goal**: 비교적 안정적인 사용자 의도와 성공 조건
- **Plan**: 현재 state/policy/resource 조건에서 Goal을 달성하기 위한 Work 구성

Plan은 version을 가질 수 있고 이전 version을 가리킬 수 있다. 이것만으로 충분하면 별도 `PlanRevision` entity를 만들지 않는다.

resource가 막혔을 때 이미 성공한 Work/Artifact는 보존하고 남은 부분만 다시 계산한다.

### 1.8 Observation / Resource State / Policy — 최소 표현

이 세 가지는 **개념적 역할**이지 반드시 세 개의 새 subsystem이라는 뜻이 아니다.

1차에서는 가능한 한 기존 구조를 재사용한다.

- Observation: Event type + generic metadata로 표현 가능
- Resource state: registry metadata/state로 표현 가능
- Policy: versioned config/blob 또는 reference로 표현 가능

예를 들어 서로 다른 provider의 quota error는 adapter가 공통 의미인 `capacity_exhausted` 같은 observation으로 정규화하되 raw detail/ref도 남긴다.

정확한 quota를 알 수 없는 경우 `unknown/estimated`와 freshness 정도만 표현하면 충분하다. 모든 provider를 완벽한 공통 schema로 만들지 않는다.

### 1.9 Planner / Execution Resolution Boundary

Planner는 Goal, 현재 Work 상태, context, policy, resource 상태를 보고 **무슨 Work가 필요한지** 정한다.

Execution Resolution은 Work가 요구하는 capability/constraints를 **어떤 concrete worker/tool/resource로 실행할지** 정한다.

- 동등한 resource로의 단순 failover는 Execution Resolution
- 범위·품질·시간·작업구조·사용자 action이 달라지는 변경은 Planner
- Pipeline은 선택된 Work를 수행하는 recipe

Planner 구현은 rule-based, LLM, hybrid 중 무엇이든 가능하며 특정 모델 prompt를 contract로 만들지 않는다.

Planner 출력은 바로 실행하지 않고 기존 contract/policy/permission/budget 검증을 통과한 뒤 Work로 materialize한다.

### 1.10 Artifact

Artifact는 문자열 URL 목록을 넘어 장기 작업 산출물의 metadata identity가 필요하다.

최소 의미:

- artifact id
- producing work/run/event
- media/type
- source owner 또는 storage reference
- version/hash where available
- created_at
- metadata

대용량 bytes 자체를 PostgreSQL에 넣는다는 뜻이 아니다.

## 2. Worker / Executor / Resource Boundary

현재 CLI adapter는 유지한다. 다만 미래 자원 라우팅을 막지 않도록 개념을 분리한다.

- **Worker/Agent**: 어떤 capability를 수행할 수 있는가.
- **Executor/Host**: 어디서 어떤 방식으로 프로세스/API를 실행하는가.
- **Provider Resource**: 어떤 provider/account/quota/credential ref를 사용하는가.

1차에서는 모든 계정 라우터를 구현하지 않는다.

### Project source vs executor workspace

현재 catalog의 `repo:C:/projects/...` 같은 host-local path를 project의 영구 source identity로 간주하지 않는다.

- project source: Git repository / logical source identity
- executor workspace: 특정 host에서 그 source가 checkout/mount된 실제 path
- WorkItem은 가능하면 logical source를 가리키고, executor가 자신의 workspace mapping으로 `cwd`를 해석한다.
- 동일 project가 local PC, AWS, Sol Pi에 각각 다른 checkout path를 가질 수 있어야 한다.
- path가 실제로 모호하거나 checkout이 없을 때만 NEED_USER 또는 provisioning work로 멈춘다.

필수 결과:

- worker metadata가 특정 로컬 PC에 구조적으로 고정되지 않는다.
- credential 값이 아닌 opaque credential/resource reference를 전달할 수 있다.
- 한 worker capability가 미래에 여러 executor를 가질 수 있는 schema seam이 있다.
- resource의 provider/model/account identity, availability, quota/capacity, rate-limit, cost class, health 같은 상태를 pipeline code가 아니라 metadata/state로 표현할 seam이 있다.
- quota를 정확히 알 수 없는 provider도 `unknown/estimated` + source/freshness/confidence로 표현할 수 있고, 실제 rate-limit/quota error observation으로 state를 갱신할 수 있다.
- 새 resource type을 추가할 때 기존 generic pipeline을 수정하지 않고 adapter + metadata/capability registration으로 참여시킬 수 있어야 한다.

## 3. Durable Persistence

현재 PostgreSQL store를 실제 개발 DB와 연결해 검증한다.

필수:

- migration clean apply
- process restart 후 run/work 조회
- NEED_USER 질문 후 restart → answer → same work/run resume
- run state transition과 event append의 transaction boundary 명확화
- append-only provenance가 runtime row 삭제에 따라 사라지지 않도록 retention/foreign-key 정책 검토. 현재 `events.run_id ... ON DELETE CASCADE`를 그대로 장기 audit 모델로 간주하지 않음
- Work/Run/Trace correlation migration 검증
- central coordination state, source-owned projection/cache, event history의 역할 분리
- context pack 생성 시 provenance/reference 유지
- context/event/artifact metadata의 민감정보 retention 정책
- idempotent external mutation의 key ownership 명확화
- retry/failover safety metadata와 uncertain side-effect reconciliation boundary
- concurrent answer/resume 방지
- cancelled/expired question 처리

Redis는 요구가 증명되기 전까지 필수가 아니다.

## 4. Durable Work Scheduling Foundation

현재 `WorkQueue`는 domain prototype으로 취급한다.

1차에서 필요한 scheduler 기반:

- persistent queued work
- atomic claim
- lease expiration
- retry/requeue
- priority
- not-before scheduling
- cancellation
- worker crash 후 recovery
- P0 interactive work가 background work보다 우선

cron/watchers의 풍부한 기능은 2차로 미룬다.

## 5. Registry and Routing

Registry는 이름 목록이 아니라 실제 실행 가능성을 반영한다.

필수:

- extensible capability descriptor registry
- worker/tool/resource/pipeline capability refs validation
- availability/health
- permission/risk metadata
- worker ↔ executor binding
- provider resource metadata/state
- tool registration
- explicit project constraints
- policy constraints
- selection provenance

선택 결과에는 최소한 "왜 이 worker/tool/executor/resource가 골라졌는가"를 trace 가능한 metadata로 남긴다.

Registry는 routing decision을 전부 소유하지 않는다. Registry는 capability 의미, 현재 후보와 상태를 제공하고, Planner/Policy가 Goal과 Plan 맥락에서 어떤 후보를 사용할지 결정할 수 있어야 한다.

현재 `Capability` contract는 description을 갖지만 `CapabilityRegistry`는 실제 descriptor registry로 사용하지 않고 worker/tool의 string set을 직접 비교한다. 1차에서는 capability를 닫힌 enum으로 만들지 않으면서 descriptor 등록/조회/validation seam을 보강한다.

Pipeline도 recipe metadata를 통해 자신이 처리하는 capability/work kind, input/output, side-effect/retry-safety를 설명할 수 있는 방향을 잡는다. 기존 `PipelineSpec.trigger`를 장기 scheduler Trigger와 혼동하지 않는다.

현재 `CapabilityRegistry.select_worker()`의 `evaluation_score → cost_score → latency` 고정 정렬과 `select_tools()`의 latency 정렬은 **초기 selection policy**로만 취급한다. 1차에서는 최소한 selection/ranking policy를 Registry 내부 불변 로직과 분리할 seam을 만든다. 모든 ranking 알고리즘을 구현할 필요는 없지만, 정책을 바꾸기 위해 Registry core를 매번 수정하는 구조로 굳히지 않는다.

현재 `BackgroundTaskClass` 같은 scheduler enum은 maintenance/research/evaluation처럼 안정적인 scheduling class로 제한한다. provider별·프로젝트별·서비스별 작업 종류를 enum에 계속 추가하는 domain taxonomy로 사용하지 않는다.

cost optimizer는 3차 대상이지만 1차 contract가 cost/budget/quota/quality metadata를 막지 않아야 한다.

## 6. Edge → Central Execution

현재 Discord shadow routing 실험을 실제 central ingress까지 연결할 준비를 한다.

Acceptance:

- casual/local request는 중앙 work를 만들지 않는다.
- project/shared-state/mutation/long-running request는 원문을 보존한 envelope로 중앙에 들어온다.
- 중앙은 edge hint를 신뢰만 하지 않고 project/risk를 재검증한다.
- duplicate delivery가 duplicate mutation을 만들지 않는다.

Discord가 첫 edge일 뿐, 중앙 ingress/execution 계약은 Web/CLI/ChatGPT에도 재사용 가능해야 한다. 각 client마다 별도 project/task state를 만들지 않는다.

기존 inventory의 ChatGPT desktop/WebMCP bridge 같은 표면은 새 중앙 계약을 소비할 adapter 후보로 검토하되, 실제 연결이 검증되지 않은 상태에서 "ChatGPT integration 완료"로 표시하지 않는다.

## 7. Web as Real Control Surface

현재 표시용 WebState를 production authority로 승격하지 않는다.

1차 Web exit criteria:

- authentication
- Manager/application chat 또는 generic work request를 제출할 수 있는 ingress
- 사용자/프로젝트 context를 owner-aware 방식으로 조립한 질의 경로
- resolve/create work
- run status
- pending question 조회
- 질문 답변
- same run resume
- artifact/result link
- project view
- worker/executor health의 최소 표시

예쁜 dashboard보다 end-to-end durability가 우선이다.

## 8. Remote Deployment and Recovery

"어느 기기에서든 중앙에 접속"은 2차 이후의 장식이 아니라 1차 완성 조건이다.

1차에서는 복잡한 HA보다 **단일 운영 인스턴스가 실제로 원격에서 안전하게 접근 가능하고 재시작 후 복구되는 것**을 먼저 증명한다.

필수:

- 현재 사용 가능한 AWS 자원을 우선 조사하되 특정 provider에 contract를 고정하지 않는다.
- HTTPS/TLS
- authenticated Web access
- 현재 `web.py`의 단순 SHA-256 password digest를 원격 노출 전 production-appropriate password KDF 또는 외부 auth로 교체
- login brute-force/rate-limit 또는 동등한 방어
- session expiry/secret rotation과 secure cookie 검증
- internal edge authentication
- persistent PostgreSQL
- process/service restart policy
- health/readiness check
- backup/restore 절차의 최소 검증
- secrets는 environment/secret owner에서 공급하고 repository/DB/event에 평문 저장하지 않음
- deployment configuration과 application state 분리

1차에서 필요하지 않은 것:

- multi-region
- Kubernetes
- active-active HA
- 복잡한 autoscaling

## 9. Eve and Manager Registration

목적은 정본 migration이 아니라 중앙 orchestration 연결이다.

### Eve

- Eve persona/world/scene 정본은 기존 owner에 둔다.
- read/status부터 adapter로 연결한다.
- Eve persona interaction과 Eve repository maintainer work를 구분한다.

### Manager

- Manager를 All Tomorrow 위 application/agent로 등록한다.
- Manager의 Notion 정본을 중앙 DB로 복제하지 않는다.
- 필요한 memory/fact retrieval은 owner-aware gateway/adapter를 통해 수행한다.
- Manager가 프로젝트 수정을 요청하면 중앙 WorkItem으로 연결할 수 있어야 한다.

## 10. Lessons — Manual First Loop

1차에서는 자동 self-learning을 서두르지 않는다.

필수:

- event/artifact/run에서 lesson candidate를 수동 생성 가능
- evidence refs 필수
- accepted/rejected 상태
- project bootstrap 시 후보 검색
- 실제 재사용 여부 기록 가능

"lesson이 저장됨"과 "전역적으로 옳은 지식"을 구분한다.

## Recommended Implementation Gates

1차 항목을 동시에 벌리지 않는다.

1. **Gate A — minimal responsibility correction**  
   Goal/Work identity, versioned Plan data, Planner vs Execution Resolution vs Pipeline 경계, source ownership, Worker/Executor/Resource seam을 최소 변경으로 확정한다. Observation/ResourceState/Policy는 기존 Event/registry/config로 표현 가능한지 먼저 확인하고 필요할 때만 새 persistence를 만든다.

2. **Gate B — durable execution and replanning substrate**  
   live PostgreSQL, durable Work/Run state, crash recovery, NEED_USER restart-resume, resource failure가 Goal을 죽이지 않고 failover/replan/wait로 이어지는 흐름을 통과한다.

3. **Gate C — routing and ingress**  
   registry/tool routing, Discord central escalation, idempotent ingress를 연결한다.

4. **Gate D — real control surface**  
   store-backed Web execution과 질문 재개를 붙이고 원격 HTTPS deployment/backup을 검증한다.

5. **Gate E — application integration**  
   Eve/Manager를 source-owner-aware adapter로 등록하고 manual lesson bootstrap까지 연결한다.

각 Gate는 앞 Gate의 invariant를 깨면 다음으로 넘어가지 않는다.

## 11. 1차 Acceptance Scenarios

1차 완성은 아래 시나리오를 모두 통과해야 한다.

### A. Any-device coding request

Web에서 repo 수정 요청 → project resolution → logical project source → WorkItem → worker/executor selection → executor-local workspace/cwd resolution → coding pipeline run → event/artifact/result 표시. 중앙 project identity가 특정 PC의 `C:\...` path에 묶이지 않음.

### B. Missing required context

repo 작업인데 cwd/mutation target이 없음 → 추정하지 않음 → NEED_USER → Web에서 답변 → process restart가 있었어도 동일 WorkItem/Run에서 재개.

### C. Discord escalation

일반 잡담은 local. 프로젝트 상태 조회 또는 mutation 요청만 중앙으로 escalation되고 trace가 연결됨.

### D. Cross-project lesson bootstrap

프로젝트 A에서 accepted lesson 생성 → 새 프로젝트 B 시작 → 관련 lesson이 자동 사실이 아니라 후보로 제시/주입되고 provenance가 보임.

### E. Crash recovery

worker/control-plane process가 실행 중 죽음 → lease 만료 → work가 유실되지 않고 안전하게 retry/recovery 가능.

### F. Domain ownership

Eve/Manager의 canonical fact를 중앙 편의를 위해 복제하지 않고 owner reference로 조회하며, 중앙 event는 orchestration provenance만 소유.

### G. Remote control surface

개발 PC 밖의 기기에서 HTTPS로 로그인 → 사용자 맥락을 owner-aware 방식으로 조회하는 질의 또는 project work 제출 → 중앙 상태에 반영 → 서버 재시작 뒤에도 work/run/history가 유지됨.

### H. Cross-system actionability

Manager/Web에서 "Eve 프로젝트의 이 문제를 고쳐" 같은 요청 → project:eve resolution → Eve canonical state를 복제하지 않은 채 repository/runtime 쪽 WorkItem 생성 → 적절한 worker/adapter 실행 → 검증 결과가 같은 중앙 trace로 돌아옴.

### I. Handover-gap test

새 worker/session이 과거 채팅 원문을 직접 보지 못하는 상태에서 project context pack을 받아 현재 목표, 핵심 결정, 금지된 변경, 열린 work, 관련 source/lesson을 복원 → 이미 결정된 사항을 다시 처음부터 묻거나 과거 결정과 정면 충돌하는 작업을 시작하지 않음.

### J. Multi-client continuity

Web에서 만든 Work/질문/결과를 Discord 또는 실제 연결 가능한 다른 client가 같은 중앙 identity로 조회·이어받음. 두 client가 별도 task/history 섬을 만들지 않음. ChatGPT/CLI adapter는 지원 표면이 검증되는 대로 같은 ingress contract를 사용함.

### K. Novel-resource extensibility

테스트용 신규 provider/resource `provider:new-free-x`를 등록 → 기존 coding/research pipeline이나 planner core에 그 이름을 추가하지 않음 → capability/resource metadata와 adapter registration만으로 후보가 됨 → policy에 맞으면 선택 가능.

### L. Resource-loss routing/replanning contract

진행 중 Work가 사용하는 resource에 quota-exhausted observation 발생 → Goal 유지 → 먼저 같은 capability/quality/policy를 만족하는 동등 resource가 있으면 Execution Resolution이 transparent failover → 그런 후보가 없고 범위·품질·시간·구조·사용자 action을 바꿔야 하면 Planner가 새 PlanRevision 생성. 현재 성공 artifact/work는 보존. 1차에서는 모든 실제 provider fallback을 구현할 필요는 없지만 두 경계가 provider-independent하게 검증되어야 함.

### M. No hard-coded pipeline branching

테스트 fixture에서 서로 다른 두 provider가 같은 `capacity_exhausted` 의미를 각자 다른 raw error로 반환 → adapter가 generic observation으로 정규화 → 동일 replanning policy가 작동. Pipeline YAML에는 두 provider 이름이나 error string 조건문이 없음.

### N. Extensible capability descriptor

새 fake capability를 descriptor로 등록 → fake worker/tool/pipeline이 capability ref를 선언 → core enum이나 provider branch 수정 없이 registry validation/selection candidate에 참여. 존재하지 않는 capability ref는 명확히 거부.

### N2. Pluggable selection policy

같은 worker/resource 후보 집합에 대해 "quality 우선"과 "free/cost 우선" policy fixture를 바꿈 → Registry 후보 데이터와 adapter는 그대로 → 선택 순서가 policy에 따라 달라짐. `CapabilityRegistry` core에 새 provider 이름이나 별도 정렬 branch를 추가하지 않음.

### O. Invalid planner output is rejected

Planner fixture가 존재하지 않는 resource를 pin하거나 hard budget을 넘기거나 acceptance criteria를 조용히 낮추는 PlanRevision 생성 → validator가 durable Work 생성 전에 거부/NEED_USER/재계획으로 돌림 → Planner 모델의 출력이 직접 실행 권한이 아님.

### P. Unknown quota state

정확한 remaining quota를 제공하지 않는 fake provider → ResourceState가 unknown/estimated로 등록 → 실제 429/quota observation이 들어오면 상태와 freshness 갱신 → provider 이름별 특수 pipeline 없이 failover/replanning boundary가 작동.

### Q. Mutation failover safety

외부 mutation worker가 timeout을 반환했지만 실제 side effect 발생 여부가 불명확함 → equivalent worker가 있어도 즉시 재실행하지 않음 → idempotency ledger/read-back/reconcile로 상태 확인 → 안전한 경우에만 retry, 아니면 NEED_USER. provider failover가 duplicate mutation을 만들지 않음.

### R. No available worker is not automatic Goal failure

required capability를 만족하는 worker/resource가 현재 0개 → pipeline-local provider branch를 추가하지 않음 → resource-unavailable Observation → WorkItem은 replan/block 상태 → Planner가 wait/resource acquisition/NEED_USER/plan change 중 policy상 가능한 경로를 선택 → Goal identity 유지.

## 12. Explicitly Not Required for 1차

- autonomous community research
- automatic service discovery/experiments
- 실제 quota-aware 최적 resource replanning 전체
- model/account cost optimizer
- large-scale API-key pool rotation
- semantic vector retrieval as mandatory dependency
- full school ingest automation
- proactive daily brief
- autonomous game demo generation
- automatic skill promotion
- production self-modification
- Kubernetes / multi-region HA
- multi-user SaaS / organization / tenant model
- GUI pipeline editor

이 기능들은 버린 것이 아니라 2차/3차의 핵심 목표다. 1차에서는 이들을 가능하게 하는 durable work/resource/provenance 경계를 확보한다.
