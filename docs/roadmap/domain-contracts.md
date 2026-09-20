# Canonical Domain Contracts

00B 이후 계획이 공유하는 identity/state 의미를 고정한다. 외부 durable backend나 provider의 내부 type/status를 이 의미로 승격하지 않는다.

## Identity glossary

### Goal

사용자가 달성하려는 장기 의미 단위. 여러 Work를 가진다.

### Work

Goal을 진전시키는 semantic unit. 사용자/프로젝트 의미, priority, constraints, lineage를 소유한다. 실행 engine의 상태를 복제하지 않는다.

### Run

Work를 실제로 수행하려는 하나의 logical attempt.

- Work 1:N Run
- 새 retry/replan attempt는 새 run_id
- 동일 Run의 crash/restart/reconciliation은 새 Run이 아님
- run_id는 external durable execution의 deterministic idempotency identity로 사용할 수 있음

### ExecutionRef

하나의 Run에 연결되는 외부 durable execution reference.

- backend
- execution_id
- execution_version
- attach metadata/version

ExecutionRef는 Run이 소유한다. Work에 단일 ExecutionRef를 저장하지 않는다. 한 Run은 동시에 둘 이상의 active logical external execution을 가져서는 안 된다.

### AgentInvocation

Run 안에서 발생한 model/agent interaction. PydanticAI의 내부 run/message object를 canonical domain으로 복제하지 않고 provenance ref만 남긴다.

### Request / Delivery

Stage 2 ingress의 identity.

- request_id: 사용자가 맡긴 논리적 요청
- delivery_id: Web/Discord/API 등의 한 전달
- client_message_id optional
- ingress/source/user/session provenance
- idempotency_key

같은 request의 duplicate delivery는 새 mutation을 만들지 않는다.

### Question

NEED_USER를 표현하는 durable semantic projection.

- question_id
- work_id/run_id
- prompt/content ref
- status: PENDING / ANSWERED / CANCELLED / EXPIRED
- answer ref
- durable signal correlation
- revision/timestamps

UI question record와 backend durable suspension primitive는 분리하며 연결은 idempotent하다.

### Artifact

큰 결과/파일/문서를 DB payload나 durable journal에 직접 복제하지 않기 위한 reference contract.

- artifact_id
- owner/source
- immutable content hash
- media/type
- storage locator 또는 logical ref
- version/supersedes
- access scope
- provenance refs
- retention class
- created_at

mutable filename/path만으로 artifact identity를 만들지 않는다.

### Trigger

durable Work를 깨우거나 생성하는 조건의 identity.

- trigger_id
- kind
- schedule/condition spec version
- owner/user/project scope
- enabled/revision
- last observed/fired refs
- idempotency window/key

### Resource

executor/model/account/quota 같은 사용 가능한 자원의 logical identity. host/provider 이름별 core branch가 아니라 capability/health/cost/authority metadata로 선택한다.

## State transitions

### Work

최소 semantic states:

- PENDING
- RUNNING
- WAITING
- SUCCEEDED
- FAILED
- CANCELLED

허용 원칙:

- terminal: SUCCEEDED / FAILED / CANCELLED
- Run 실패가 Work를 자동 FAILED로 만들지는 않음. policy가 replan/new Run 여부를 결정
- WAITING은 사용자/외부 조건을 기다리는 semantic 상태이며 backend wait status의 복사본이 아님
- terminal Work를 수정해 재실행하지 않고 successor Work 또는 명시적 revision policy를 사용

### Run

최소 states:

- STARTING
- RUNNING
- WAITING
- SUCCEEDED
- FAILED
- CANCEL_REQUESTED
- CANCELLED

원칙:

- STARTING은 application commit 후 external start/attach가 아직 확정되지 않은 상태
- cancellation은 요청과 완료를 구분
- external backend status를 그대로 enum에 복사하지 않음
- terminal Run을 같은 run_id로 새로운 attempt로 재사용하지 않음

## Cancellation semantics

- Work cancel: 새 Run 생성 금지 + active Run에 cancel request 전달
- Run cancel: cooperative request. 외부 mutation이 이미 commit된 사실을 되돌렸다고 가정하지 않음
- side effect 중간 cancellation은 adapter의 reconciliation 결과가 확정될 때까지 terminal success/failure를 위조하지 않음
- terminal Run cancel은 idempotent no-op 또는 already_terminal 결과
- missing execution과 backend unavailable은 서로 다른 error category

## Provenance invariant

최소 연결:

Request/Trigger
→ Goal
→ Work
→ Run
→ ExecutionRef
→ AgentInvocation / Tool/Worker call
→ Artifact/Result/Event

모든 연결은 ID/ref로 가능해야 하며 raw external object serialization에 의존하지 않는다.
