# Control Plane Semantic Contracts

00B 이후 Goal/Work/Run 외에 모든 stage가 공유하는 control-plane 의미를 정의한다.

## Goal

GoalRecord 최소 필드:

- goal_id
- user_id
- project_id optional
- title/objective
- status: ACTIVE | WAITING | SUCCEEDED | FAILED | CANCEL_REQUESTED | CANCELLED
- completion_policy_ref
- priority/commitment
- revision
- created_at/updated_at/terminal_at

### Goal transition

- ACTIVE → WAITING: 사용자/외부 조건 때문에 새 Work 진행 불가
- WAITING → ACTIVE: blocking condition 해결
- ACTIVE/WAITING → SUCCEEDED: completion policy가 Outcome evidence를 검증
- ACTIVE/WAITING → FAILED: 더 이상 허용된 Work/replan path가 없고 failure policy가 terminal을 판정
- ACTIVE/WAITING → CANCEL_REQUESTED → CANCELLED

Goal success는 "모든 Work row가 terminal"만으로 자동 결정하지 않는다.

## Work / active Run rule

기본 invariant:

- Work 1:N historical Run
- 기본 max_active_runs_per_work = 1
- speculative/parallel Run은 별도 policy가 명시적으로 허용한 경우에만 가능
- parallel Run을 허용할 때 winner/merge/cancel-losers semantics와 side-effect class를 미리 선언
- ordinary retry/replan은 prior Run을 terminal로 만든 뒤 새 Run 생성

Run SUCCEEDED가 Work SUCCEEDED를 자동 의미하지 않는다.
RunResult → Work completion evaluator가 expected outcome을 검증한 뒤 Work terminal transition을 결정한다.

## Outcome / CompletionEvidence

성공 판정을 공통 구조로 남긴다.

OutcomeRecord:

- outcome_id
- target_type: GOAL | WORK | RUN | EXPERIMENT | DEPLOYMENT
- target_id
- status: SATISFIED | NOT_SATISFIED | INCONCLUSIVE
- criterion_ref/version
- evidence_refs[]
- artifact_refs[]
- observed_values
- evaluator_ref/version
- created_at

CompletionEvidence 없이 semantic Work/Goal을 SUCCEEDED로 바꾸는 operation은 금지한다.
단순 transport 성공/exit_code=0은 Run execution evidence일 뿐 Work objective 충족 증거가 아니다.

## Event

EventRecord:

- event_id
- event_type
- schema_version
- occurred_at
- recorded_at
- actor_ref
- subject refs: request/goal/work/run/trigger/proposal optional
- correlation_id
- causation_event_id optional
- idempotency_key optional
- payload_ref 또는 bounded non-secret metadata
- source_ref optional

규칙:

- event_type/schema_version은 persisted compatibility data
- 같은 idempotency scope에서 duplicate Event를 만들지 않음
- occurred_at만으로 ordering하지 않고 event_id tie-break
- Event는 audit/domain fact이며 trace span dump가 아님
- historical Event update/delete는 privileged maintenance policy 없이는 금지

## Error contract

CanonicalError:

- category
- code
- retryability
- ambiguity
- authority/security relevance
- external_ref optional
- safe_message
- evidence_refs
- caused_by optional

최소 category:

- NOT_FOUND
- UNAVAILABLE
- TIMEOUT
- RATE_LIMITED
- INVALID_INPUT
- INVALID_STATE
- CONFLICT
- PERMISSION_DENIED
- AUTHENTICATION_FAILED
- AMBIGUOUS_EFFECT
- RETRY_EXHAUSTED
- INVARIANT_VIOLATION
- VERSION_INCOMPATIBLE
- RESOURCE_EXHAUSTED
- UNSUPPORTED

adapter는 provider/backend-specific exception을 이 contract로 normalize한다.
UNKNOWN/AMBIGUOUS를 success/not-found로 축소하지 않는다.

## SourceRef

- source_owner_id
- source_type
- source_id
- version/revision/hash
- canonical_locator
- observed_at
- freshness policy/ref
- access scope
- read/write authority metadata

derived summary/cache는 SourceRef의 canonical owner를 대체하지 않는다.

## Project

ProjectRecord:

- project_id
- owner_user_id
- title/status: ACTIVE | ARCHIVED
- source_refs[]
- default authority/policy refs
- allowed executor/resource scope
- created_at/updated_at

Project archive는 source repository나 artifact를 자동 삭제하지 않는다.
project membership/role은 Authorization contract에서 관리한다.

## ToolDescriptor

- tool_id/version
- source_owner
- input/output schema refs
- capabilities
- side_effect_class: READ_ONLY | IDEMPOTENT_REPLAY | RECONCILE_BEFORE_RETRY | NON_RETRYABLE_AMBIGUOUS
- required_authority
- timeout/resource class
- idempotency key support
- cancellation support
- provenance/source ref

## WorkerDescriptor

- worker_id/version
- capabilities
- supported artifact/workspace types
- authority scope
- side-effect capabilities
- cancellation semantics
- timeout/output limits
- health/ref freshness
- adapter version

## Authorization Decision

ActionAuthorization:

- decision_id
- actor/user/session ref
- action type
- target/source refs
- requested capability
- risk/protection class
- result: ALLOW | CONFIRM | DENY
- policy_ref/version
- reason/evidence
- expiry/nonce if CONFIRM

일반 external mutation도 protected self-change와 별개로 authorization을 거친다.
파일 삭제, Git push, external account mutation, production write 등은 tool 이름이 아니라 capability/risk metadata로 판단한다.

## Account / project roles

최소 role:

- owner
- editor
- viewer

single-user deployment에서도 schema/authorization은 owner identity를 명시한다.
향후 multi-user가 필요해도 object owner/user scope를 다시 정의하지 않도록 한다.

## Cost / Usage

UsageRecord:

- usage_id
- run/tool/model/resource ref
- quantity + unit
- estimated_or_actual
- currency optional
- price_table_ref/version optional
- provider observation ref
- occurred_at

unknown price/usage를 0으로 기록하지 않는다.

## Time semantics

- absolute deadlines: timezone-aware UTC instant + original timezone/ref optional
- user calendar deadline: local timezone + logical date/time
- operation timeout: monotonic duration
- wall-clock deadline과 process timeout을 같은 필드로 쓰지 않는다.

## Cancellation propagation

Goal cancel:

1. CANCEL_REQUESTED
2. 새 Work/Run/Trigger 생성 차단
3. open child Work에 cancel policy 적용
4. active Run cooperative cancel
5. pending Question cancel/supersede
6. Goal-owned one-shot/recurring trigger disable 여부를 policy로 결정
7. ambiguous external effect reconciliation
8. children이 terminal/repair 상태에 도달한 뒤 Goal CANCELLED

즉시 cascade delete하지 않는다.
