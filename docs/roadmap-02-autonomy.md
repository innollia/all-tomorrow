# 2차 완성 — Reliable Assistant & Remote Control

> Status: **Planned.** 1차의 self-improving researcher와 durable kernel이 실제 운영 조건에서 닫힌 뒤 시작한다.

## Definition of Done

2차가 끝나면 All Tomorrow는 혼자 연구만 잘하는 시스템이 아니라, 사용자가 어디서든 일을 맡길 수 있고 그 요청을 끝까지 책임지는 **믿을 만한 개인 비서형 control plane**이 된다.

핵심은 "연구원 위에 요청 처리 기능을 붙인다"이지, 1차 researcher를 버리고 새 구조를 만드는 것이 아니다.

사용자 요청은 durable Goal/Work로 들어가고, 적절한 worker/tool/resource로 실행되며, 필요한 경우 질문으로 멈췄다가 같은 맥락으로 재개되고, 결과와 provenance를 다시 확인할 수 있어야 한다.

## Gate A — Real User Ingress

지원 표면:

- authenticated Web UI
- Discord central escalation
- CLI / API
- 이후 가능한 다른 client

모든 ingress는 같은 Goal/Work authority를 사용한다.

각 client가 별도 task/history 섬을 만들지 않는다.

Discord는 모든 메시지를 중앙에 보내지 않고 local 처리 가능한 대화는 local에 남긴다.

## Gate B — Any-Device Remote Control

AWS의 항상 켜진 중앙 runtime을 실제 사용자 control surface로 사용한다.

필수:

- HTTPS
- authenticated Web access
- secure session
- persistent PostgreSQL
- process restart recovery
- health/readiness check
- 최소 backup/restore
- secrets separation

현재 표시용 WebState를 authority로 승격하지 않는다. Web은 실제 store-backed Goal/Work/Run 상태를 보여주고 사용자 요청과 질문 답변을 연결해야 한다.

## Gate C — Reliable Request Execution

사용자 요청은 다음 흐름으로 처리한다.

    user request
    → project / intent resolution
    → Goal or Work
    → context assembly
    → worker/tool/resource resolution
    → pipeline/run
    → artifact/result
    → evaluation / follow-up

필수:

- durable NEED_USER
- restart-safe resume
- idempotent mutation
- uncertain side-effect reconciliation
- cancellation
- retry/replan
- project context handover
- artifact/result retrieval

Run 실패가 Goal을 자동으로 죽이지 않는다.

## Gate D — Project Context and Handover

새 worker/session이 과거 전체 채팅을 직접 보지 못해도 현재 프로젝트를 이어갈 수 있어야 한다.

중앙은 다음을 coordination state로 유지한다.

- current objective
- current constraints/invariants
- decision/source refs
- open Goal/Work
- relevant artifact/result/lesson refs

Git/Eve/Manager/Discord가 소유하는 canonical fact를 중앙 편의를 위해 새 정본으로 복제하지 않는다.

bounded context pack을 만들어 worker에 전달하고 provenance를 보존한다.

## Gate E — Worker / Model / Resource Routing

1차의 LiteLLM/model gateway와 Antigravity/OpenCode/Codex worker를 실제 요청 처리에 사용한다.

All Tomorrow가 orchestration authority를 유지한다.

provider/model/account의 특수성은 adapter/gateway metadata로 격리한다.

필수:

- worker capability
- availability/health
- permission/risk
- provider/model metadata
- budget/cost telemetry
- selection provenance
- fallback/replan

선택 정책은 Registry 내부의 고정 sort로 영구 고정하지 않는다.

## Gate F — Cross-System Actionability

한 곳에서 발견한 문제가 다른 프로젝트의 실제 Work로 이어질 수 있어야 한다.

예:

- Web에서 Eve 프로젝트 문제를 보고
- project:eve를 resolve하고
- repository/runtime Work를 만들고
- 적절한 worker가 수정/검증하고
- 결과를 같은 중앙 trace로 돌려줌

이 단계에서 Eve/Manager의 전체 personal application 기능까지 완성할 필요는 없다.

## User Request Priority

1차에서 만든 user-owned priority policy를 실제 assistant 요청 처리에 적용한다.

현재 사용자 정책의 중요한 예:

- 학교 수행평가 또는 AI 활용 대회 참여처럼 실제 commitment가 높은 요청은 잘못 돌고 있던 background/autonomous work보다 우선한다.
- "이거 재밌겠다, 한번 만들어봐" 같은 낮은 commitment의 발화는 반드시 즉시 실행하지 않고 TODO/Goal 후보로 해석할 수 있다.

시스템은 일정·현재 workload·사용자 맥락을 이용해 충돌 자체를 사전에 줄여야 한다.

## 2차 Acceptance Scenarios

### A. Any-device work

노트북이 아닌 기기에서 Web 로그인 → project work 제출 → AWS 중앙에 durable Work 생성 → 적절한 executor/worker 실행 → 결과 확인.

### B. Restart-safe NEED_USER

필수 정보 부족 → NEED_USER → 중앙 재시작 → Web에서 답변 → 같은 Work에서 재개.

### C. Multi-client continuity

Web에서 만든 Work/질문/결과를 Discord 또는 CLI에서 같은 identity로 조회/이어받음.

### D. Cross-system action

Manager/Web에서 다른 프로젝트의 실제 수정 요청 → 올바른 project/source owner를 유지한 채 Work 생성 → 수정/검증 → trace 유지.

### E. Handover-gap test

새 worker/session이 과거 채팅 없이 context pack만 받고 현재 목표·핵심 결정·금지 변경·열린 Work를 복원해 작업을 이어감.

### F. Resource failure

선호 provider/worker failure → generic observation → 가능한 fallback 또는 replan → Goal 유지 → provenance 유지.

### G. User-priority preemption

background researcher가 자율 Goal을 실행 중 high-priority user request 수신 → background yield → user Work 우선 → 이후 background Goal은 정책에 따라 재개/보류.

## Explicitly Not Required for 2차

- full Manager personal operations
- school material automatic ingest
- proactive daily personal brief
- complete calendar integration
- broad multi-host repo synchronization
- full API-key farm optimization
- autonomous long-horizon game demo
- every external service watcher
- multi-user SaaS

2차의 핵심은 **사용자가 시킨 일을 어디서든 안정적으로 맡기고 이어서 끝내는 비서**다.
