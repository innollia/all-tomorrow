# All Tomorrow Roadmap Index

이 문서는 세부 구현 항목을 끝없이 쌓는 backlog가 아니라, README의 최종 목적이 구현 과정에서 축소되거나 다른 목표로 치환되지 않도록 잡아두는 계획 인덱스다.

## Planning Rule

모든 작업은 아래 순서로 판단한다.

1. README의 Original Vision과 Additional Hard Requirements에 실제로 기여하는가.
2. 현재 completion stage의 첫 사용자 체감 목표를 전진시키는가.
3. 기존 owner/adapter/pipeline/event 경계를 깨지 않고 구현할 수 있는가.
4. 특정 provider/project/failure 이름을 core orchestration에 하드코딩하지 않고 capability/state/policy/adapter로 일반화할 수 있는가.
5. 지금 필요하지 않은 미래 복잡도를 미리 구현하고 있지 않은가.
6. 실행 중 조건이 바뀌어도 Goal/provenance/user control을 유지할 수 있는가.
7. 자기개선이 권한·비용·통제 경계를 넓히는 경우 ADR 0004의 외부 승인 경계를 우회하지 않는가.

구현 편의를 위해 최종 목적을 작게 다시 정의하지 않는다. 반대로 최종 목적에 있다는 이유만으로 모든 미래 기능을 1차에 밀어 넣지도 않는다.

## Product Order

사용자가 체감할 완성 순서는 다음과 같다.

1. **Researcher** — 스스로 공부하고, 문제를 발견하고, 자기 자신까지 개선하는 두뇌
2. **Reliable assistant** — 사용자가 시킨 일을 어디서든 안정적으로 맡고 이어서 끝내는 비서
3. **Personal manager** — 학교·일정·일상·프로젝트를 함께 운영하는 관리자

이 순서는 구현 의존성과 동일하지 않다.

Researcher가 첫 완성품이 되려면 그 아래에 먼저 최소 durable kernel, evaluation, rollback, budget, provenance가 필요하다.

## Generality Gate

새 기능은 "문제 종류 → 대응"을 core나 pipeline에 추가하는 방식으로 만들지 않는다.

검산 기준:

1. Work layer는 문제를 미리 이해하지 못해도 결과와 사건을 중앙에 남길 수 있는가.
2. Metacognition은 그 기록을 보고 새로운 문제나 기회를 스스로 발견할 수 있는가.
3. 해결 방법이 사전에 목록에 없어도 조사, 새 Work, 새 Goal, system improvement로 이어질 수 있는가.
4. 새 provider/tool/project 때문에 generic core에 이름별 branch가 늘지 않는가.
5. 자기 자신의 prompt/policy/code도 같은 observation/evaluation 흐름의 대상이 될 수 있는가.
6. 특정 기능을 만들기 위해 reflection reviewer, API-problem handler 같은 추상적 하드코딩을 추가하고 있지 않은가.

## Completion Model

1차/2차/3차는 capability milestone이다.

각 stage는 사용자에게 보이는 하나의 완성된 역할을 닫는다.

### 1차 완성 — Durable Self-Improving Researcher

문서: [roadmap-01-foundation.md](roadmap-01-foundation.md)

질문:

> 시스템이 restart를 견디는 중앙 상태 위에서 스스로 문제와 기회를 발견하고, 새 Goal/Work를 만들고, 자신의 prompt/policy/code까지 평가·개선하며, 허용된 변경은 자동 적용 후 보고하고 보호 변경은 노트북 Approval Authority 없이는 적용하지 못하는가?

1차의 첫 구현물은 durable kernel이지만 첫 완성품은 researcher다.

### 2차 완성 — Reliable Assistant & Remote Control

문서: [roadmap-02-autonomy.md](roadmap-02-autonomy.md)

질문:

> 사용자가 어느 기기에서든 일을 맡기고, 그 요청이 durable Goal/Work로 남아 적절한 worker/tool/resource로 실행되고, 질문·중단·재시작을 견디며, 다른 client에서도 같은 상태를 이어받을 수 있는가?

2차에서 All Tomorrow는 연구원 위에 믿을 만한 개인 비서가 된다.

### 3차 완성 — Personal Manager & Generalized Autonomy

문서: [roadmap-03-evolution.md](roadmap-03-evolution.md)

질문:

> 연구원과 비서가 학교·일정·지식·프로젝트·장기 자율 작업까지 owner-aware하게 연결되어, 사용자가 매번 직접 지시하지 않아도 지속적인 개인 운영을 수행할 수 있는가?

3차에서 개인 관리자와 넓은 장기 자율 운영을 닫는다.

## Original Vision Coverage

| 원문에서 요구한 결과 | 주 stage | 닫히는 기준 |
|---|---|---|
| 시스템이 스스로 문제를 발견하고 진화 | 1차 | unknown-problem diagnosis + autonomous Goal + self-improvement loop |
| 반성/메타인지 방식 자체도 다시 개선 | 1차 | metacognition이 자기 prompt/policy/evaluation 기록을 관찰하고 개선 |
| 요청이 없어도 조사·실험 지속 | 1차→3차 | 1차 researcher loop, 3차 broad watcher/long-horizon operation |
| 자동 자기수정 | 1차 | ordinary change 자동 promotion/report, protected change external approval |
| 여러 모델/API/CLI 사용 | 1차→2차 | LiteLLM/model gateway + Antigravity/OpenCode/Codex worker, 이후 reliable routing |
| 어느 기기에서든 웹으로 중앙 접속 | 2차 | AWS remote HTTPS authenticated control surface |
| 흩어진 ChatGPT/Discord/CLI 작업을 중앙에서 조정 | 2차 | shared Goal/Work authority + multi-client continuity |
| 사용자가 시킨 일을 중단·재개하며 끝까지 수행 | 2차 | durable request execution + NEED_USER + crash recovery |
| 한 곳에서 다른 프로젝트 실제 수정 | 2차 | cross-system Work creation and execution |
| 프로젝트 노하우 재사용 | 2차→3차 | context/lesson candidate + outcome-based cross-project loop |
| 학교 프린트 처리 | 3차 | artifact → extraction → owner → actionable Work |
| 일정/할 일 기반 proactive brief | 3차 | owner-aware scheduled personal report |
| 새로운 AI 서비스 자동 탐색·시험 | 3차 | research/experiment/resource candidate loop |
| 무료 asset 수집 | 3차 | watcher → artifact catalog with provenance |
| 여러 기기/서버 자원 활용 | 2차→3차 | 2차 routing contract, 3차 multi-executor growth |
| 유휴 자원으로 game demo 제작 | 3차 | multi-day autonomous Goal → playable artifact → feedback iteration |

## Cross-Stage Architecture Invariants

1. **Original vision is constitutional** — 원문 요구와 파생 설계가 충돌하면 파생 설계를 수정한다.
2. **Control Plane is shared authority, not a serial brain** — 중앙 state를 여러 흐름이 함께 사용한다.
3. **Work and metacognition run in parallel** — 작업과 시스템 관찰을 하나의 직렬 chain으로 묶지 않는다.
4. **Metacognition can observe itself** — 별도 meta-meta 계층을 무한히 쌓지 않는다.
5. **Pipeline is an execution recipe** — 문제 종류와 대응표를 Pipeline에 쌓지 않는다.
6. **No closed problem taxonomy** — 앞으로 만날 문제와 해결책을 미리 열거했다고 가정하지 않는다.
7. **Durable work is above runs** — 하나의 Goal/Work는 여러 run과 시간대를 견딘다.
8. **Source ownership survives centralization** — 기존 정본을 중앙 편의 때문에 복제 정본으로 만들지 않는다.
9. **Evaluation before self-change** — ordinary self-change도 sandbox/evaluation/rollback 경계를 가진다.
10. **Protected authority is external** — 권한·비용·통제 경계를 넓히는 변경은 노트북 Approval Authority 승인 없이는 production 적용 불가.
11. **No silent user-choice substitution** — 추론된 선호를 이유로 명시적 선택을 몰래 바꾸지 않는다.
12. **User-owned priority dominates autonomous work** — high-priority user commitment는 background work보다 우선한다.
13. **Ask instead of fabricating** — 필수 정보가 없으면 추정으로 밀어붙이지 않는다.

## Runtime Placement Strategy

### AWS

항상 켜진 중앙 runtime의 첫 운영 위치.

초기 역할:

- PostgreSQL / central state
- researcher triggers
- model/API work
- background research
- Goal/Work queue
- reports

### Laptop

1차 repo mutation의 기본 executor.

또한 ADR 0004의 Approval Authority를 호스팅한다.

1차에서는 laptop 하나의 workspace mapping만 실제로 구현한다. multi-host workspace synchronization은 3차 쪽으로 미룬다.

## User Work Priority

priority는 user-owned policy로 해석한다.

현재 중요한 예:

- 학교 수행평가와 AI 활용 대회 참여처럼 실제 commitment가 높은 요청은 background/autonomous work를 yield시키고 가용 자원을 우선 사용한다.
- "이거 재밌겠다. 한번 만들어봐." 정도의 낮은 commitment 발화는 즉시 실행보다 TODO/Goal 후보로 남길 수 있다.

이 예를 generic core의 학교/대회 switch문으로 만들지 않는다.

## Current Position

2026-09-19 현재 위치는 **1차 초반 — durable researcher kernel 구축 전환점**이다.

이미 있는 기반:

- provider-independent contracts
- versioned pipeline runtime
- NEED_USER suspend/resume
- run/question persistence abstraction
- PostgreSQL migration
- append-only event/trace
- worker registry
- Antigravity/OpenCode CLI adapters
- Discord edge policy
- minimal authenticated Web surface
- initial scheduler/lesson/evaluation objects

현재 다음 구조가 아직 필요하다.

- durable Goal/Work layer
- restart-safe researcher loop
- autonomous Goal generation
- mixed evaluation
- self-improvement lifecycle
- ordinary auto-promotion + rollback
- protected change classification
- laptop Approval Authority
- LiteLLM gateway
- Codex worker
- AWS always-on researcher deployment
- daily researcher report

## Roadmap Maintenance

- README의 Original Vision 원문은 요약문으로 대체하지 않는다.
- stage 이동은 요구 삭제가 아니다. 어느 stage에서 닫히는지 포인터를 남긴다.
- 새 기능이 최종 목적과 직접 연결되지 않으면 기본적으로 backlog 후보로 둔다.
- 현재 stage의 첫 역할을 닫는 데 필요하지 않은 외부 integration은 뒤로 민다.
- 실제 구현이 문서와 달라졌으면 완료라고 쓰기 전에 Current Position/Architecture/해당 stage 문서를 갱신한다.
- protection boundary 변경은 문서 편집만으로 효력이 생긴 것으로 간주하지 않는다. 실제 Approval Authority와 deployment permission으로 강제해야 한다.

## Architecture Decisions

- [ADR 0001 — Separate Control Plane Repository](decisions/0001-control-plane-boundary.md)
- [ADR 0002 — Durable Work Above Pipeline](decisions/0002-durable-work-above-pipeline.md)
- [ADR 0003 — Parallel Metacognition Over Case-Based Orchestration](decisions/0003-generic-planning-over-hardcoded-pipelines.md)
- [ADR 0004 — Self-Modification Authority and External Approval Boundary](decisions/0004-self-modification-and-approval-boundary.md)

## Work Discipline

각 변경은 inspect → plan → implement → test → inspect diff → verify 순서로 수행한다.

작업 종료 시 적절한 event/decision/project state에 최소한 다음을 남긴다.

- 무엇을 바꿨는가
- 왜 바꿨는가
- 무엇을 검증했는가
- 결과
- 남은 문제
- architecture decision 발생 여부
- lesson 후보

거대한 누적 handover 문서를 history 원본으로 만들지 않는다.
