# Stage 3.2 — Trigger and Knowledge Expansion

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 3.1 + Stage 2 durable assistant
- 지금 시작 가능: **아니오**

## Goal

장기 personal/project operation에 필요한 trigger와 cross-project knowledge를 확장한다.

## Trigger Scope

- recurring schedule
- one-shot schedule
- calendar/event
- webhook
- polling/condition watcher
- idle-resource trigger
- system-generated trigger

Trigger는 durable Goal/Work를 깨우거나 생성한다.

## Knowledge Loop

run/event/artifact
→ lesson candidate
→ evidence/evaluation
→ accepted lesson
→ bootstrap/context candidate
→ reuse outcome

필수:

- provenance
- scope
- freshness/version
- conflict handling
- actual reuse outcome
- retirement/review

vector DB는 구현 옵션이지 정본이 아니다.

## Done When

restart-safe trigger와 실제 cross-project reuse outcome이 같은 중앙 provenance로 연결된다.
