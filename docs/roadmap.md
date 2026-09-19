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

상태: 기본 계약 및 단위 테스트 구현. provider-independent contract는 유지 중이다.

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

상태: YAML loader, 순차/분기 실행, 버전 고정, `NEED_USER` 중단·재개, run store 기반 재시작 후 재개 구현. 운영 환경의 전체 장애 복구 검증은 남았다.

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

상태: PostgreSQL migration과 run/question store 구현, in-memory 원자적 재개 및 PostgreSQL 트랜잭션 코드가 있다. live PostgreSQL 통합 테스트와 run state + event append 원자성은 미완료다.

- PostgreSQL migration
- projects/tasks/runs/run_steps/events/pipeline_versions/user_questions
- transactional run state + append-only event
- pending question query
- restart 후 resume 검증

Redis와 pgvector는 이 phase의 필수 조건이 아니다.

## Phase 4 — Registry

상태: Worker binding 및 selection/pipeline 실행 slice 구현 완료. Tool live discovery 및 risk metadata 확장은 진행 예정.

- worker/tool/capability metadata
- health와 availability
- risk/permission metadata
- mock worker 및 fake adapter selection tests
- `WorkerService`: CapabilityRegistry metadata와 executable WorkerAdapter를 1:1 consistent binding (mismatch/duplicate 거부)
- Pipeline nodes `capability.select` 및 `worker.run` (`agent.run` alias) 구현
- Data-driven coding pipeline (`pipelines/coding.yaml`) 및 missing cwd `NEED_USER` resume 지원
- Event provenance 기록 및 민감정보(prompt, task, secret, payload) 누출 방지

실제 연결 가능한 worker만 등록한다. 이름만 있는 Codex/OpenCode/Antigravity integration은 만들지 않는다.

## Phase 5 — First real adapters

상태: CLI worker adapter (AntigravityWorker, OpenCodeWorker)의 runtime pipeline dispatch 연동 완료. Eve read-only MCP adapter 코드는 있으나 운영 연결 검증은 미완료. DiscordService read adapter와 Manager bridge adapter는 미구현.

우선순위:

1. Eve read-only/status adapter using existing MCP
2. DiscordService-compatible read adapter
3. 기존 Antigravity Manager bridge adapter (참고: CLI worker adapter인 AntigravityWorker/OpenCodeWorker와는 별개의 매니저 브릿지)

각 adapter는 source owner, timeout, idempotency, error mapping, trace propagation을 명시한다.

## Phase 6 — Discord edge experiment

상태: 순수 policy와 테스트 구현. 최신 Eve `origin/main` 기반 별도 worktree `C:\projects\eve-control-plane-edge`에서 Discord shadow routing을 구현·테스트했으나, Eve 본 저장소에 통합·배포하지 않았다. 중앙 실행으로의 실제 escalation은 아직 없다.

- pure routing policy와 fixture dataset
- `LOCAL_REPLY`, `LOCAL_TOOL`, `CENTRAL_QUERY`, `CENTRAL_TASK`, `PROJECT_ACTION`, `USER_CLARIFICATION`
- 기존 bot과 충돌하지 않는 shadow decision logging
- 충분히 검증한 뒤에만 central escalation 활성화

일반 대화가 중앙 run을 만들지 않는 것을 acceptance test로 둔다.

## Phase 7 — Minimal API and Web

상태: 인증, Projects/Runs/Questions 표시용 API와 Discord edge 결정 API만 구현. Chat 실행, store-backed run/question 조회, 질문 답변 후 동일 run 재개, worker status UI는 미구현이다. 현재 `WebState` 목록을 production 정본으로 취급하지 않는다.

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

