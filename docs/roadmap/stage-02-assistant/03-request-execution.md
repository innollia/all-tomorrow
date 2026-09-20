# Stage 2.3 — Reliable Request Execution

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.1 + Stage 1 durable kernel
- 지금 시작 가능: **아니오**
- contracts: ../domain-contracts.md, ../failure-recovery-contract.md, ../data-security-artifact-contract.md

## 목적

canonical Request를 bounded context와 적절한 executor/tool로 실행하고 질문·실패·cancel·restart에도 Goal을 잃지 않는다.

## Flow

Request
→ project/intent resolution
→ Goal/Work
→ ContextPack
→ resource/tool/worker resolution
→ Run + durable execution
→ Artifact/Result
→ evaluation/follow-up

## ContextPack contract

ContextPack은 과거 채팅 dump가 아니다.

최소:

- context_pack_id/version
- objective
- explicit user constraints
- invariant/authority refs
- project/source-owner refs
- relevant decisions
- open Goal/Work/Run refs
- selected Artifact/result/lesson refs
- unresolved Questions
- freshness timestamps/versions
- source provenance
- token/byte budget

### Selection

우선순위:

1. current explicit user request/constraint
2. canonical owner source
3. accepted current project decisions/invariants
4. active Goal/Work state
5. relevant artifacts/lessons
6. historical conversation summary only when source-owned facts를 대체하지 않음

conflict는 silently merge하지 않는다.
owner/source/version이 충돌하면 authoritative source를 택하거나 NEED_USER/diagnostic evidence로 남긴다.

token/byte ceiling을 config로 고정하고 exceed 시 deterministic ranking/truncation + omitted refs summary를 남긴다.

## Cancellation

canonical contract:

- Request/Work cancel은 새 Run 생성 차단
- active Run에 cooperative cancel request
- external mutation ambiguity는 cancellation success로 위조하지 않고 reconciliation
- cancel 완료 전 CANCEL_REQUESTED
- terminal Work/Run late cancel idempotent
- cancel 후 user re-run은 새 Request/Run identity

## Retry/replan

- Run retry/recovery와 semantic replan 구분
- same Run crash recovery는 same run_id
- 다른 strategy/worker/model로 새 logical attempt는 새 Run
- Run failure가 Goal 자동 failure 아님
- replan decision + evidence + prior Run refs 저장

## NEED_USER

Question projection + durable wait.
answer는 exact question/work/run scope와 idempotency identity를 가진다.
다른 client에서 answer해도 same durable wait resume.

## Artifact/result

large result는 ArtifactRef.
mutable path만 result identity로 사용하지 않는다.
worker/tool output integrity/hash와 source owner를 기록한다.

## Requirements

| ID | 요구 | Level |
|---|---|
| 2.3-01 bounded ContextPack으로 새 session handover | L1 |
| 2.3-02 conflicting source가 silent merge되지 않음 | L0/L1 |
| 2.3-03 cancel 중 ambiguous side effect reconciliation | L2 |
| 2.3-04 failed Run→new Run replan + same Work provenance | L1/L2 |
| 2.3-05 NEED_USER other client resume | L2/L3 |
| 2.3-06 restart 후 same Goal/Work | L2 |
| 2.3-07 ArtifactRef/hash retrieval | L1 |

## 완료조건

새 worker/session이 bounded ContextPack만으로 현재 objective/constraints/source를 복원하고 cancel/replan/question/restart에서도 provenance와 identity를 유지해야 한다.
