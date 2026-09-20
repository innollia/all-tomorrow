# Stage 3.2 — Trigger and Knowledge Expansion

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 3.1 + Stage 2 durable assistant
- 지금 시작 가능: **아니오**
- contracts: ../domain-contracts.md, ../failure-recovery-contract.md

## 목적

restart-safe trigger engine과 evidence-backed knowledge lifecycle을 추가한다.

# Trigger system

## Trigger kinds

- recurring schedule
- one-shot schedule
- calendar/event
- webhook
- polling/condition watcher
- idle-resource
- system-generated

kind는 adapter capability이며 core state machine은 공통이다.

## Trigger state

TriggerRecord:

- trigger_id
- owner/user/project scope
- kind
- spec + spec_version
- enabled
- revision
- timezone if temporal
- misfire_policy
- idempotency policy/window
- last_observed_ref
- last_fired_logical_key
- next_due/condition cursor if applicable
- created/updated timestamps

## Fire semantics

Trigger fire는 TriggerDelivery 같은 durable identity를 생성한다.

- trigger_id + logical_fire_key unique
- duplicate callback/poll/scheduler wake → Work 최대 1개
- revision mismatch인 old fire 무효
- disabled/cancelled trigger는 새 Work 생성 금지
- Work creation 실패 시 delivery state가 재시도/repair 가능

## Schedule/misfire

- timezone-aware
- DST fold/gap fixture
- one-shot consumed state
- recurring missed fire: SKIP / FIRE_ONCE / CATCH_UP_BOUNDED 중 versioned policy
- unbounded catch-up 금지

## Webhook

- source authentication/signature
- replay timestamp/nonce
- payload size/content-type limits
- secret redaction
- delivery id dedup

## Condition watcher

- last observation/cursor durable
- false→true edge인지 level-trigger인지 spec에 명시
- poll failure와 condition false 구분
- repeated true가 duplicate Work를 만들지 않는 policy

# Knowledge lifecycle

run/event/artifact
→ LessonCandidate
→ evaluation
→ AcceptedLesson
→ context/bootstrap candidate
→ actual reuse
→ outcome evaluation
→ confidence/freshness update
→ retire/review

## Lesson record

- lesson_id/version
- scope: user/project/global-like but authority-bounded
- claim/strategy
- evidence refs
- contradiction refs
- confidence
- accepted_by/policy ref
- freshness/expiry/review_at
- supersedes/conflicts
- reuse_count
- outcome refs

## Acceptance

lesson을 모델이 한 번 말했다고 accepted로 만들지 않는다.
acceptance policy는 evidence type/quality와 scope를 versioned rule로 정의한다.

conflicting accepted lessons는 silently merge하지 않는다. scope/freshness/evidence로 resolve하거나 conflict state를 유지한다.

## Reuse outcome

ContextPack에 lesson을 넣은 사실이 성공이 아니다.

- 실제 어떤 Work/Run이 lesson을 사용했는지 provenance
- outcome이 baseline/expected direction과 일치했는지
- harmful/no-effect outcome
- confidence update/retirement

을 기록한다.

## Requirements

- duplicate schedule/webhook/poll → Work 1개
- trigger update/cancel old delivery 무효
- DST/misfire
- webhook replay/auth failure
- watcher restart cursor
- conflicting lessons preserved
- stale lesson exclusion/review
- actual reuse outcome links back to lesson

## 완료조건

trigger는 restart/duplicate/time 변화에 안전하고 lesson은 evidence→reuse→outcome까지 provenance가 닫혀야 한다.
