# Architecture

## 1. 시스템 경계

All Tomorrow는 application이 아니라 Control Plane이다. 중앙이 소유하는 것은 authority와 공유 상태이며, 실행은 edge와 worker에 분산된다. 아래 그림은 목표 구조이며, 현재 구현 완료도를 나타내지 않는다.

```text
Discord/Web/CLI/ChatGPT
        │
        ▼
   Edge Agent
   ├─ local reply/tool
   └─ escalation envelope
        │
        ▼
All Tomorrow Control Plane
   ├─ request/project/capability resolution
   ├─ versioned pipeline runtime
   ├─ project/task/run/event authority
   ├─ pending user questions
   └─ adapter dispatch
        │
        ├─ Eve adapter ─────> Eve MCP/runtime ──> Eve-owned Notion/Postgres
        ├─ Manager adapter ─> Antigravity bridge
        ├─ Worker adapters ─> Codex/OpenCode/other workers
        └─ Tool adapters ───> MCP/native tools
```

### 중앙이 소유하는 정본

- project identity와 등록된 repository/environment 참조
- 중앙 task와 run 상태
- versioned pipeline specification
- execution event와 trace linkage
- pending user question과 resume state
- worker/tool/capability registry metadata
- lesson candidate 및 검증 상태

### 중앙이 소유하지 않는 정본

- Eve persona/world/scene canonical state
- Manager persona와 대화 세션 내부 상태
- 각 Git repository의 코드와 Git history
- Discord 원본 메시지
- Notion에 이미 owner가 있는 Manager/Eve domain facts
- provider secret 값

## 2. 핵심 invariant

1. Clients, models, workers, tools, pipelines는 교체 가능하다.
2. Project history, canonical state, accumulated knowledge, user control은 그 교체에서 살아남는다.
3. Central authority does not imply central execution.
4. No new knowledge island.
5. Ask rather than hallucinate ownership.
6. Preserve provenance.

## 3. V1 bounded context

```text
edge         local/central 판단과 escalation envelope
pipeline     spec load, validation, node execution, branch, resume
projects     project identity와 source ownership
tasks        user-visible work item
runs         pipeline 실행 상태
events       append-only history
questions    NEED_USER lifecycle
registry     worker/tool/capability metadata
adapters     외부 시스템 경계
```

V1에서는 Memory, Evaluation, Background Research를 확장 가능 경계로만 남기고 자동화하지 않는다.

## 4. Core contracts

현재 구현된 핵심 계약은 다음과 같다.

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

### ExecutionContext

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

`NEED_USER`는 `question`, `reason`, `blocked_step`, `resume_token`, `required_fields`를 요구한다. resume token은 임의 pipeline 입력이 아니라 저장된 run/step과 일회성 또는 만료 정책으로 연결한다.

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

Spec은 immutable version으로 저장한다. 활성 버전 변경은 새 run에만 적용하고, 진행 중인 run은 시작 당시 version을 유지한다.

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

Event는 append-only history다. canonical projection은 event와 별도이며, event 수정으로 현재 상태를 고치지 않는다.

## 5. Pipeline runtime

현재 runtime은 DAG 엔진이 아니라 명시적 순차 step과 제한된 조건 분기만 지원한다. `WorkerService`가 capability metadata와 실제 CLI adapter를 묶고, `capability.select`와 `worker.run` node가 `pipelines/coding.yaml`에서 이를 사용한다. 실행 상태는 `RunStateStore`에 저장되며, `NEED_USER` 답변은 동일 run/step/version으로 재개된다.

- YAML/JSON spec load와 schema validation
- node type registry
- `${step.output}` 형태의 안전한 변수 참조
- 순차 실행
- 명시적 condition/branch
- retry policy의 횟수와 backoff metadata
- 모든 step 결과 event 기록
- `NEED_USER`에서 run 정지
- 답변 검증 후 동일 run/version/step resume
- cancellation

초기 비목표:

- 임의 코드 expression 평가
- 동적 plugin 설치
- 무한 loop
- 분산 transaction
- GUI editor
- production에서 spec in-place 수정

## 6. Edge escalation

Edge는 최소한 다음 signal을 계산한다.

```text
needs_shared_memory
needs_project_state
needs_cross_project_knowledge
needs_remote_tool
needs_long_running_task
needs_canonical_mutation
```

모두 false이면 local 처리 가능하다. 하나 이상 true여도 자동 중앙 실행을 강제하지 않고, policy 결과와 원문을 envelope로 보낸다. 중앙 resolver가 project와 risk를 다시 검증한다.

Edge policy는 YAML로 정의하며 pure classifier 테스트가 있다. 기존 Discord bot에는 별도 Eve worktree에서 shadow routing만 연결했다. 실제 central escalation과 해당 Eve 브랜치의 통합·배포는 아직 완료되지 않았다.

## 7. Source ownership

| Domain | Owner | 중앙 접근 |
|---|---|---|
| Central project/task/run/event | All Tomorrow PostgreSQL | 직접 service |
| Pipeline specs | Git의 YAML + DB version record | loader/publisher |
| Eve scene/persona/world | 기존 Eve Notion/PostgreSQL/runtime | Eve adapter |
| Manager canonical facts | 기존 Notion owner | Manager memory adapter |
| Discord messages | Discord | Discord service/cache adapter |
| Repository code/history | Git repository | repo tool adapter |
| Large artifacts | 향후 object storage | metadata pointer |
| Secrets | 외부 secret store | opaque key reference |

동일 사실을 여러 저장소에 쓰는 adapter는 projection임을 명시하고 owner/version/provenance를 함께 기록한다.

## 8. Persistence

V1 영속화는 PostgreSQL을 우선한다. pgvector는 lesson retrieval 요구가 실제 구현되는 단계까지 필수 dependency로 넣지 않는다. Redis도 요구가 증명되기 전에는 추가하지 않고 Postgres 기반 claim/queue로 시작한다.

최소 논리 테이블 후보:

```text
projects
project_sources
tasks
runs
run_steps
events
pipeline_versions
user_questions
workers
tools
capabilities
registry_bindings
```

`migrations/0001_core.sql`과 `0002_lessons.sql`에 초기 DDL이 있다. 다만 local live PostgreSQL 검증이 없고 run state 업데이트와 event append의 단일 트랜잭션 보장도 미완료다. 현재 Web API의 runs/questions 목록은 이 저장소의 영속 상태와 연결되지 않는다.

## 9. Security와 mutation

- credential 값은 contract/event/log에 기록하지 않는다.
- adapter는 최소 권한의 opaque credential reference만 받는다.
- canonical write와 high-risk tool은 중앙 policy 확인이 필요하다.
- mutation 대상 repository/project가 둘 이상이면 `NEED_USER`로 멈춘다.
- idempotency key는 외부 mutation adapter의 필수 입력으로 한다.
- trace가 없는 외부 mutation은 허용하지 않는다.

## 10. 새로운 지식 섬 검산

이 설계는 새 중앙 저장소를 만들지만 새 도메인 정본 섬을 만들지 않는다.

- All Tomorrow의 고유 정본은 cross-system orchestration 데이터뿐이다.
- Eve/Manager/Discord facts는 원 owner에 남는다.
- adapter는 복제 저장이 아니라 참조와 provenance를 기록한다.
- edge-local cache는 canonical state로 승격되지 않는다.
- pipeline/trace/event는 모든 client가 공유한다.
