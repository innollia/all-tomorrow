# ADR 0002: Durable Work Above Pipeline

Status: Accepted

Date: 2026-09-19

## Context

초기 구현은 `RequestEnvelope → Pipeline → Worker → Run/Event` 흐름을 중심으로 빠르게 기반을 만들었다.

이 구조는 한 번의 요청을 실행하고 `NEED_USER`로 중단·재개하는 엔진으로는 유효하다. 하지만 README의 Original Vision은 한 요청보다 오래 살아 있는 요구를 포함한다.

- 여러 프로젝트 사이에서 경험을 누적하고 재사용
- 사용자의 즉시 요청이 없어도 background work 수행
- 새 서비스 발견·시험·편입
- 여러 기기·서버·provider 자원 오케스트레이션
- 학교/개인 운영의 proactive brief
- 여러 날에 걸친 실제 game demo 같은 산출물
- 성과와 실패를 바탕으로 한 measured self-improvement
- 서로 다른 채팅/worker 사이의 handover gap 감소

이 요구를 Pipeline 자체에 계속 추가하면 pipeline이 goal manager, scheduler, resource pool, memory, self-improvement controller까지 소유하는 monolith가 된다.

또한 현재 CLI Worker는 capability와 local execution location이 한 adapter에 붙어 있어 미래의 multi-host/provider resource routing을 직접 표현하기 어렵다.

ADR 0001의 별도 Control Plane repository/source-ownership 경계는 유지한다. 이 ADR은 그 위에서 초기 `task/run/pipeline` 해석을 장기 Goal/Work 구조로 확장한다.

## Decision

### 1. Goal/Work는 Pipeline보다 위에 둔다

- Goal은 여러 WorkItem과 여러 run에 걸쳐 살아남는 목적이다.
- WorkItem은 durable하게 추적·대기·재시도되는 수행 단위다.
- Run은 WorkItem을 특정 Pipeline version으로 실행한 한 시도다.
- Pipeline은 WorkItem을 실행하는 versioned recipe다.

`RequestEnvelope`는 ingress contract이며 장기 Work identity가 아니다.

### 2. Work/Run/Trace identity를 분리한다

- `work_id`: 장기 작업 identity
- `run_id`: execution attempt
- `trace_id`: distributed execution trace
- parent/causation refs: child work와 여러 run의 관계

기존 `runs.trace_id UNIQUE`를 Work identity 대신 사용하지 않는다.

### 3. Project coordination context를 중앙에 둔다

중앙은 raw chat 전체나 domain canonical data를 복제하는 대신, cross-system orchestration에 필요한 project coordination projection과 source/provenance refs를 유지한다.

새 worker/session에는 이 projection과 source-owner 조회를 조립한 bounded context pack을 전달한다.

### 4. Worker와 execution resource의 분리를 허용한다

개념적으로 다음을 분리한다.

- Worker/Agent: capability
- Executor/Host: execution location/mechanism
- Provider Resource: provider/account/quota/credential reference

현재 Antigravity/OpenCode CLI adapter는 초기 구현으로 유지한다. 즉시 전면 재작성하지 않고 future separation을 막지 않는 seam을 만든다.

Project의 logical source identity와 executor별 checkout/workspace path도 분리한다. 한 Windows PC의 `C:/projects/...`를 cross-system project source 정본으로 사용하지 않는다.

### 5. Existing pipeline/event/adapter work는 유지한다

이 결정은 기존 runtime을 버리는 재작성 결정이 아니다.

유지할 기반:

- PipelineSpec versioning
- NodeResult
- NEED_USER/resume
- append-only event 방향
- source-owner adapter boundary
- capability registry
- edge local/central policy

## Consequences

장점:

- background work와 장기 프로젝트가 Pipeline lifecycle에 억지로 종속되지 않는다.
- 한 Work가 여러 실행 시도와 worker 교체를 견딘다.
- scheduler/watchers/self-improvement를 later stage에 추가해도 core 의미를 다시 뒤집지 않아도 된다.
- 새 worker가 과거 chat 전체를 몰라도 project context pack으로 현재 상태를 복원할 수 있다.
- provider/account/host 자원이 늘어날 때 capability model을 유지할 수 있다.

비용:

- 기존 thin `tasks` schema와 run correlation을 재검토해야 한다.
- Goal/Work/Trigger/Artifact/project-context persistence가 추가된다.
- worker selection과 execution binding 사이에 한 단계가 늘어난다.

## Guardrails

- Goal/Work를 이유로 모든 domain fact를 All Tomorrow DB에 복제하지 않는다.
- Pipeline을 장기 orchestration state의 정본으로 만들지 않는다.
- Event log 하나를 current project context 대신 사용하지 않는다.
- 미래 기능을 예상한다는 이유만으로 1차에 모든 provider/watcher/self-improvement 구현을 넣지 않는다.
- 실제 요구가 없는 distributed-system complexity는 추가하지 않는다.
