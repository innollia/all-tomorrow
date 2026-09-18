# Phased Implementation Plan

각 phase는 `inspect → plan → implement → test → inspect diff → verify` 순서로 수행한다. 다음 phase로 넘어가기 전 README 원문과 architecture invariant를 검산한다.

## Phase 0 — Inventory and boundaries

상태: 문서 기준 완료, live system 검증은 미수행.

- 기존 repository와 integration surface 조사
- source ownership 초안 작성
- 재사용 지점과 금지할 복제 식별
- production code 미작성

Exit criteria:

- 중앙 저장소와 Eve 저장소의 ownership이 분리되어 있다.
- 확인되지 않은 integration을 사실처럼 문서화하지 않는다.
- 새 knowledge island 검산을 통과한다.

## Phase 1 — Core Contracts

범위:

- `RequestEnvelope`
- `ExecutionContext`
- `NodeResult`와 모든 status
- `PipelineSpec`
- `Event`
- `Project`, `Worker`, `Capability`, `Tool`, `UserQuestion`
- schema validation과 contract unit tests

결정 전 확인할 사항:

- Python/FastAPI를 실제 첫 runtime으로 확정할지
- package/build/test 표준
- identifier와 timestamp 규칙

Exit criteria:

- invalid contract는 명확한 field-level error로 거부된다.
- `NEED_USER` payload의 필수 필드가 강제된다.
- contract에 provider-specific SDK type이 새지 않는다.

## Phase 2 — Minimal Pipeline Runtime

범위:

- YAML spec loader
- immutable version identity
- node registry와 공통 interface
- 순차 실행과 제한된 branch
- variable resolution
- error/retry/cancel
- in-memory trace/event sink
- `NEED_USER` suspend/resume

Acceptance scenario:

1. 같은 runtime code로 두 YAML의 step 순서가 다르게 실행된다.
2. 한 node가 `NEED_USER`를 반환한다.
3. runtime은 이후 node를 실행하지 않고 resume token을 만든다.
4. 사용자 답변 후 동일 pipeline version과 blocked step에서 재개한다.
5. 원 실행과 재개 실행이 같은 trace/run에 연결된다.

## Phase 3 — Event Store

- PostgreSQL migration
- projects/tasks/runs/run_steps/events/pipeline_versions/user_questions
- transactional run state + append-only event
- pending question query
- restart 후 resume 검증

Redis와 pgvector는 이 phase의 필수 조건이 아니다.

## Phase 4 — Registry

- worker/tool/capability metadata
- health와 availability
- risk/permission metadata
- mock worker로 selection tests

실제 연결 가능한 worker만 등록한다. 이름만 있는 Codex/OpenCode/Antigravity integration은 만들지 않는다.

## Phase 5 — First real adapters

우선순위:

1. Eve read-only/status adapter using existing MCP
2. DiscordService-compatible read adapter
3. 기존 Antigravity Manager bridge adapter — **완료** (AntigravityWorker + OpenCodeWorker)

각 adapter는 source owner, timeout, idempotency, error mapping, trace propagation을 명시한다.

## Phase 6 — Discord edge experiment

- pure routing policy와 fixture dataset
- `LOCAL_REPLY`, `LOCAL_TOOL`, `CENTRAL_QUERY`, `CENTRAL_TASK`, `PROJECT_ACTION`, `USER_CLARIFICATION`
- 기존 bot과 충돌하지 않는 shadow decision logging
- 충분히 검증한 뒤에만 central escalation 활성화

일반 대화가 중앙 run을 만들지 않는 것을 acceptance test로 둔다.

## Phase 7 — Minimal API and Web

- authentication 선택은 비용/외부 가입 결정을 사용자에게 질문한 뒤 확정
- Chat, Projects, Runs, Questions
- 질문 답변과 run resume
- worker status

## Phase 8 — Manager and Eve registration

- `project:eve` 등록
- Eve persona runtime과 Eve Maintainer routing 분리
- Manager app을 중앙 위 application으로 등록
- Notion migration 없이 Memory Gateway adapter 연결

## Phase 9 — Lessons

- event에서 수동 lesson candidate 생성
- project bootstrap 시 후보 검색
- provenance와 reuse evidence
- 자동 global skill 승격 없음

## Deferred

- research watcher
- autonomous background experiments
- self-improvement promotion
- pgvector semantic retrieval
- model cost optimizer
- GUI pipeline editor
- school ingest full automation
- scheduled brief
- game generation
- graph database
- Kubernetes/multi-region HA

## 매 작업 종료 기록

각 작업은 event/decision/project state의 올바른 위치에 다음을 남긴다.

- 무엇을 바꿨는가
- 왜 바꿨는가
- 무엇을 테스트했는가
- 결과
- 남은 문제
- architecture decision 발생 여부
- lesson 후보

거대한 누적 handover 파일은 만들지 않는다.

