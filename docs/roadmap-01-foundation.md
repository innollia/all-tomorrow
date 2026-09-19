# 1차 완성 — Durable Central Core

> Status: **In progress.** 현재 구현은 이 단계의 초기 실행 엔진이며, 다음 구조 작업은 Gate A다.


## Definition of Done

1차 완성은 "pipeline 몇 개가 실행된다"가 아니다.

사용자가 어느 기기에서든 중앙에 작업을 맡기고, 그 Work가 durable하게 실행·중단·재개되며 결과와 provenance를 다시 확인할 수 있어야 한다. 동시에 Work가 남긴 중앙 state/event를 **작업과 독립된 observer가 읽고 후속 Work를 만들 수 있는 seam**이 있어야 한다.

1차가 끝나면 시스템은 아직 자율 연구원이나 자기개선 시스템은 아니지만, 이후 2차·3차 기능이 core 재작성 없이 올라갈 수 있는 중앙 기반이어야 한다.

## Immediate Next Work

Gate A에서는 새 framework를 만들지 않고 현재 구조에 두 가지 seam만 확보한다.

1. Goal/Work/Run의 durable identity를 바로잡는다.
2. Work 실행이 남기는 Event/state를 **별도 metacognition flow가 읽고 새 Work를 만들 수 있게** 한다.
3. `capability.select` 같은 현재 실행 선택 로직은 Work layer 안의 초기 구현으로 유지하되 최종 정책으로 고정하지 않는다.
4. 필요한 최소 migration/test만 추가한다.

1차의 목표는 "메타인지 AI 완성"이 아니라 **작업 계층 밖에서 시스템 전체를 관찰하고 개입할 수 있는 자리**를 만드는 것이다.

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

### 1.1 Goal / Work / Run

- Goal: 여러 작업을 넘어 유지되는 목적
- WorkItem: 실제 수행되는 durable 작업
- Run: WorkItem의 한 실행 시도

Run 하나의 실패가 자동으로 Work/Goal 실패가 되지 않는다.

### 1.2 Shared Central State

Work가 수행되면 결과·질문·실패·artifact·event를 중앙에 남긴다.

이 기록은 다음 Work뿐 아니라 **메타인지 계층의 관찰 입력**이 된다. 특정 문제 taxonomy를 먼저 만들 필요는 없다.

### 1.3 Parallel Metacognition Seam

1차에서는 별도 거대 planner를 만들지 않는다.

필요한 것은:

- 중앙 state/event를 작업 실행과 독립적으로 읽을 수 있음
- observer가 이상/정체/반복을 발견하면 새 Work 또는 proposal을 생성할 수 있음
- 여러 observer가 동시에 존재할 수 있음
- observer가 작업 실행의 필수 직렬 단계가 아님

실제 고급 관찰·원인추론·외부조사는 2차/3차에서 확장한다.

### 1.4 Project Coordination Context

handover gap을 줄이기 위해 중앙은 현재 목표, 제약, 결정/source ref, 열린 Work, 관련 결과/lesson ref를 유지한다.

Worker에는 raw Request만 던지지 않고 필요한 project context를 조립해 전달한다.

### 1.5 Artifact

Artifact는 producing work/run과 provenance를 추적할 수 있는 metadata identity를 가진다.
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

### K. Metacognition seam

테스트는 원인을 미리 알려주지 않는다.

Work가 반복해서 기대한 결과를 내지 못하거나 진행이 멈추는 fixture를 만든다. Work layer는 있는 그대로 Run/Event를 남긴다.

별도 observer가 이를 읽어:

- "정상 진행이 아니다"라고 판단하고
- 추가 확인이 필요하다는 새 Work/proposal을 만들며
- 원래 Goal을 잃지 않는지

를 검증한다.

fixture의 실제 원인이 resource, tool, input, environment 중 무엇인지는 observer에게 사전 분류값으로 주지 않는다.


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
