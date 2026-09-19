# Stage 2.3 — Reliable Request Execution

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.1 + Stage 1 durable kernel
- 지금 시작 가능: **아니오**

## Goal

사용자 요청을 적절한 context/worker/tool/resource로 실행하고 끝까지 책임지는 assistant path를 만든다.

## Flow

user request
→ project / intent resolution
→ Goal or Work
→ context assembly
→ worker/tool/resource resolution
→ pipeline/run
→ artifact/result
→ evaluation/follow-up

## Scope

- durable NEED_USER
- restart-safe resume
- idempotent mutation
- uncertain side-effect reconciliation
- cancellation
- retry/replan
- project context handover
- artifact/result retrieval
- Run failure가 Goal을 자동으로 죽이지 않음

## Context

중앙은 coordination state만 소유한다.

- current objective
- constraints/invariants
- decision/source refs
- open Goal/Work
- relevant artifact/result/lesson refs

Git/Eve/Manager/Discord의 canonical fact를 새 중앙 정본으로 복제하지 않는다.

## Done When

새 worker/session이 과거 채팅 전체 없이 bounded context pack으로 현재 작업을 이어갈 수 있고, 실패/질문/restart에도 Goal을 잃지 않는다.
