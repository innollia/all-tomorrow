# 1차 완성 — Durable Central Core

## Definition of Done

1차 완성은 "pipeline 몇 개가 실행된다"가 아니다.

사용자가 어느 기기에서든 중앙에 들어와 요청을 보내면, 그 요청이 적절한 project와 durable work에 연결되고, 필요한 pipeline/worker/tool로 실행되며, 중간에 사용자 정보가 필요하면 즉시 멈추고 질문하고, 서버 재시작 뒤에도 같은 work/run을 재개하고, 결과·산출물·provenance를 다시 확인할 수 있어야 한다.

1차가 끝나면 시스템은 아직 자율 연구원이나 자기개선 시스템은 아니지만, 이후 2차·3차 기능이 core 재작성 없이 올라갈 수 있는 중앙 기반이어야 한다.

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

중앙은 raw chat 전체를 새 정본으로 복제하는 대신, cross-system project coordination에 필요한 현재 projection과 provenance reference를 유지한다.

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

Project context는 Git 코드, Eve state, Manager personal facts의 복제 정본이 아니다. 그 값들이 필요하면 source reference를 통해 읽는다.

### 1.7 Artifact

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

필수 결과:

- worker metadata가 특정 로컬 PC에 구조적으로 고정되지 않는다.
- credential 값이 아닌 opaque credential/resource reference를 전달할 수 있다.
- 한 worker capability가 미래에 여러 executor를 가질 수 있는 schema seam이 있다.

## 3. Durable Persistence

현재 PostgreSQL store를 실제 개발 DB와 연결해 검증한다.

필수:

- migration clean apply
- process restart 후 run/work 조회
- NEED_USER 질문 후 restart → answer → same work/run resume
- run state transition과 event append의 transaction boundary 명확화
- append-only provenance가 runtime row 삭제에 따라 사라지지 않도록 retention/foreign-key 정책 검토. 현재 `events.run_id ... ON DELETE CASCADE`를 그대로 장기 audit 모델로 간주하지 않음
- Work/Run/Trace correlation migration 검증
- project coordination projection과 event history의 역할 분리
- context pack 생성 시 provenance/reference 유지
- context/event/artifact metadata의 민감정보 retention 정책
- idempotent external mutation의 key ownership 명확화
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

- capability
- availability/health
- permission/risk metadata
- worker ↔ executor binding
- tool registration
- explicit project constraints
- selection provenance

선택 결과에는 최소한 "왜 이 worker/tool/executor가 골라졌는가"를 trace 가능한 metadata로 남긴다.

cost optimizer는 3차 대상이지만 1차 contract가 cost/budget metadata를 막지 않아야 한다.

## 6. Edge → Central Execution

현재 Discord shadow routing 실험을 실제 central ingress까지 연결할 준비를 한다.

Acceptance:

- casual/local request는 중앙 work를 만들지 않는다.
- project/shared-state/mutation/long-running request는 원문을 보존한 envelope로 중앙에 들어온다.
- 중앙은 edge hint를 신뢰만 하지 않고 project/risk를 재검증한다.
- duplicate delivery가 duplicate mutation을 만들지 않는다.

Discord가 첫 edge일 뿐, 계약은 Web/CLI/ChatGPT에도 재사용 가능해야 한다.

## 7. Web as Real Control Surface

현재 표시용 WebState를 production authority로 승격하지 않는다.

1차 Web exit criteria:

- authentication
- submit request
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

1. **Gate A — contracts and schema correction**  
   Goal/Work/Trigger/Artifact identity, Work/Run/Trace correlation, project coordination context, source ownership, Worker/Executor/Resource seam을 확정하고 migration 계획을 만든다.

2. **Gate B — durable execution**  
   live PostgreSQL, transactional event/run state, durable scheduling, crash recovery, NEED_USER restart-resume를 통과한다.

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

Web에서 repo 수정 요청 → project resolution → WorkItem → coding pipeline → worker selection → executor run → event/artifact/result 표시.

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

## 12. Explicitly Not Required for 1차

- autonomous community research
- automatic service experiments
- model/account cost optimizer
- large-scale API-key pool rotation
- semantic vector retrieval as mandatory dependency
- full school ingest automation
- proactive daily brief
- autonomous game demo generation
- automatic skill promotion
- production self-modification
- Kubernetes / multi-region HA
- GUI pipeline editor

이 기능들은 버린 것이 아니라 2차/3차의 핵심 목표다. 1차에서는 이들을 가능하게 하는 durable work/resource/provenance 경계를 확보한다.
