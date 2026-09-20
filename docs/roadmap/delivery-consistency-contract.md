# Delivery, Consistency & Repair Contract

application DB와 외부 durable/tool/source system 사이의 모든 dual-write seam을 공통 방식으로 다룬다.

## 1. Delivery primitive

외부 action을 요구하는 application-side durable intent를 DeliveryRecord로 표현할 수 있다.

- delivery_id
- kind
- subject/request/work/run/trigger/question refs
- destination adapter/resource ref
- idempotency_key
- payload/artifact ref
- status: PENDING | DISPATCHING | DELIVERED | AMBIGUOUS | FAILED | REPAIR_REQUIRED | CANCELLED
- attempts
- last_error_ref
- next_attempt_at
- created_at/updated_at

custom execution queue를 다시 만드는 목적이 아니다.
Delivery는 **cross-store intent/reconciliation record**이며 ordering/worker scheduling은 durable backend 소유다.

## 2. Outbox boundary

다음은 application transaction 안에서 semantic state + Delivery intent를 함께 commit한다.

- Run STARTING → durable execution start intent
- Question ANSWERED → backend signal intent
- Trigger fire → Work materialization intent
- Artifact metadata/reference attach after durable object write
- external source mutation request
- outbound user message/notification

DB commit 후 dispatcher/reconciler가 external action을 수행한다.

external system이 deterministic idempotency/get-by-key를 제공하면 same key로 회수한다.
제공하지 않으면 side-effect class에 따라 reconcile/NEED_USER/repair로 이동한다.

## 3. Inbox / inbound dedup

외부 delivery/webhook/callback/worker result에는 source delivery/event identity를 저장한다.

- source
- source_event_id
- observed_at
- payload hash/ref

unique scope로 동일 inbound event를 한 번만 materialize한다.

## 4. Idempotency key lifecycle

각 key에 scope와 retention을 정의한다.

- scope: user/project/action/resource 등
- created_at
- valid_until 또는 retention class
- target/result ref

TTL 이후 같은 key가 재사용되면 무조건 동일 request로 취급하지 않는다.
API contract가 key reuse window를 명시한다.

hash collision/format collision을 막기 위해 namespace + version을 포함한다.

## 5. Question answer → signal

1. answer를 Question revision과 함께 DB commit
2. signal Delivery intent 생성
3. backend signal(signal_id=question answer identity)
4. delivered 확인
5. duplicate signal은 backend/adapter contract상 idempotent
6. terminal/superseded Question의 late answer는 새 Run을 자동 시작하지 않음

## 6. Artifact write → ref attach

1. artifact bytes를 temporary/object storage에 write
2. content hash verify
3. immutable object finalize
4. Artifact metadata + ref attach transaction
5. attach 실패 시 orphan object는 GC candidate
6. DB ref가 있는데 bytes/hash가 없으면 integrity failure/repair

## 7. Source mutation

Git/API/account mutation:

- mutation intent + authorization + expected source version
- external apply
- resulting source version/hash fetch
- provenance commit

apply 성공 여부가 ambiguous하면 expected version/hash/idempotency lookup으로 reconciliation.
blind second mutation 금지.

## 8. Compensation

이미 commit된 effect를 되돌릴 수 있는 action은 optional CompensationSpec을 가진다.

- original delivery/effect ref
- compensation capability/tool
- preconditions
- expected inverse effect
- authorization requirement
- evidence

compensation은 transaction rollback과 같은 것으로 취급하지 않는다.
보상 자체도 새 external mutation이며 실패/ambiguity가 가능하다.

## 9. Repair queue / dead-letter semantics

자동 reconciliation budget을 소진한 Delivery/Run/Trigger는 삭제하지 않는다.

REPAIR_REQUIRED record가 포함:

- failed subject/delivery
- last known semantic state
- ambiguity
- attempted repairs
- recommended operator actions
- safe retry capability
- affected Goal/Work

Remote Control surface에서 목록/inspect/retry/resolve/abandon 기능을 제공한다.
operator repair도 Authorization + Event를 남긴다.

## 10. OutboundDelivery

사용자에게 먼저 보내는 질문/보고/알림:

- outbound_id
- user/channel
- message/artifact ref
- purpose
- idempotency_key
- status: PENDING | SENT | DELIVERED | FAILED | EXPIRED
- provider_message_id optional
- attempts/error
- created_at

질문 record 생성과 실제 push 성공을 같은 것으로 보지 않는다.
duplicate retry가 동일 알림을 반복 전송하지 않도록 provider/delivery idempotency를 사용한다.
