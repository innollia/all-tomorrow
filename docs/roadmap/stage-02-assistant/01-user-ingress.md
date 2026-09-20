# Stage 2.1 — User Ingress

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 1 완료
- 지금 시작 가능: **아니오**
- contracts: ../domain-contracts.md, ../plan-verification-contract.md

## 목적

Web/Discord/CLI/API delivery를 하나의 canonical Request contract로 normalize하되 local conversation을 불필요하게 중앙 Work로 승격하지 않는다.

## Canonical records

### Request

- request_id
- user_id
- project_id optional
- objective/content ref
- attachment ArtifactRefs
- origin
- authority/requested capability
- priority/commitment metadata
- idempotency_key
- created_at

### Delivery

- delivery_id
- request_id
- ingress kind
- client_message_id/event_id optional
- session/account ref
- received_at
- raw-content owner/ref
- delivery metadata

같은 logical Request가 여러 Delivery를 가질 수 있다.

## Idempotency

ingress-specific stable key를 canonical request idempotency key로 map한다.

- Web: explicit client request id 또는 generated id returned before retry
- Discord: channel/message/event identity
- API/CLI: required Idempotency-Key for mutation endpoint, absence policy 명시

DB unique constraint로 duplicate concurrent delivery가 Goal/Work mutation을 두 번 만들지 못하게 한다.
application pre-check만 사용하지 않는다.

## Normalize boundary

ingress adapter가 담당:

- authentication identity
- delivery identity
- raw input/attachment refs
- transport metadata
- request normalization

core가 담당:

- project/intent/commitment interpretation
- Goal/Work materialization
- authority decision

## Local vs central escalation

Discord/local client는 모든 메시지를 중앙 Work로 보내지 않는다.

명시적 deterministic preconditions:

central candidate:
- 사용자가 durable task/action을 요청
- 다른 project/resource mutation 필요
- background/restart-safe execution 필요
- 중앙 Goal/Work 상태 질의/변경

local 가능:
- 단순 대화/표현
- durable state가 필요 없는 즉시 답변

불확실하거나 mutation authority가 필요한 경우 local model의 임의 추측이 아니라 central resolution 또는 사용자 질문으로 넘긴다.

escalation decision + reason/version을 provenance로 남긴다.

## Attachments

attachment bytes를 Request row에 복제하지 않는다.
Data/Artifact contract의 ArtifactRef를 사용하고 access scope를 유지한다.

## Requirements

| ID | 요구 | 검증 | Level |
|---|---|---|---|
| 2.1-01 | 모든 ingress가 same Request/Delivery contract | adapter contract | L0 |
| 2.1-02 | concurrent duplicate delivery → mutation 1개 | DB concurrent test | L1 |
| 2.1-03 | attachment는 ArtifactRef | storage test | L1 |
| 2.1-04 | auth user/source provenance 보존 | integration | L1 |
| 2.1-05 | local conversation이 불필요한 Work 생성 안 함 | fixture |
| 2.1-06 | escalation ambiguity가 silent mutation 안 함 | negative |

## 완료조건

서로 다른 ingress의 동일 요청이 하나의 canonical identity로 수렴하고 duplicate delivery와 local/central 경계가 observable policy로 검증되어야 한다.
