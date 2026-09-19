# All Tomorrow Roadmap Index

이 문서는 세부 구현 항목을 끝없이 쌓는 backlog가 아니라, README의 최종 목적이 구현 과정에서 축소되거나 다른 목표로 치환되지 않도록 잡아두는 계획 인덱스다.

## Planning Rule

모든 작업은 아래 순서로 판단한다.

1. README의 `Original Vision`과 `Additional Hard Requirements`에 실제로 기여하는가.
2. README의 `Derived Final Goals` 중 어떤 목표를 전진시키는가.
3. 현재 completion stage의 exit criteria에 필요한가.
4. 기존 owner/adapter/pipeline/event 경계를 깨지 않고 구현할 수 있는가.
5. 지금 필요하지 않은 기능을 미래 가능성만으로 과설계하고 있지 않은가.

구현 편의를 위해 최종 목적을 작게 다시 정의하지 않는다. 반대로 최종 목적에 있다는 이유만으로 모든 미래 기능을 1차 완성에 밀어 넣지도 않는다.

## Completion Model

### 1차 완성 — Durable Central Core

문서: [roadmap-01-foundation.md](roadmap-01-foundation.md)

질문:

> 사용자가 어느 기기에서든 중앙에 작업을 맡기고, 그 작업이 durable한 Goal/Work/Run 상태로 남으며, 적절한 pipeline/worker/tool로 실행되고, 필요한 경우 질문으로 멈췄다가 같은 맥락으로 재개되며, 결과와 provenance를 다시 확인할 수 있는가?

1차는 현재 요청 처리 엔진을 **장기 시스템의 올바른 중심부**로 고치는 단계다.

### 2차 완성 — Autonomous Personal & Project Operations

문서: [roadmap-02-autonomy.md](roadmap-02-autonomy.md)

질문:

> 사용자가 즉시 요청하지 않아도 중앙이 허용된 스케줄·watcher·background work를 durable하게 발생시키고, 프로젝트 간 지식을 재사용하고, 개인 운영과 프로젝트 운영을 같은 authority 아래 연결할 수 있는가?

2차부터 시스템은 반응형 도구를 넘어 지속적으로 움직이는 운영자가 된다.

### 3차 완성 — Measured Self-Evolving System

문서: [roadmap-03-evolution.md](roadmap-03-evolution.md)

질문:

> 시스템이 새로운 도구·서비스·노하우를 스스로 탐색하고 시험하며, 실제 장기 산출물을 만들고, 자신의 성과를 측정해 개선 후보를 만들고, 검증된 변경만 안전하게 승격·롤백할 수 있는가?

3차는 README 원문의 가장 공격적인 자율성과 자기개선 목표를 닫는 단계다.

## Cross-Stage Architecture Invariants

아래는 stage가 올라가도 유지한다.

1. **Original vision is constitutional**  
   원문 요구와 파생 설계가 충돌하면 파생 설계를 수정한다.

2. **Control Plane is a means**  
   중앙 authority는 최종 목적의 인프라다. 사용자의 장기 운영·학습·생산·자율성을 희생하면서 Control Plane 자체를 완성하는 것을 성공으로 보지 않는다.

3. **Pipeline is an execution recipe**  
   pipeline 안에 장기 goal, scheduler, resource accounting, self-improvement 전체를 욱여넣지 않는다.

4. **Durable work is above runs**  
   하나의 Goal/WorkItem은 여러 run, worker, tool, 시간대를 가질 수 있다. run은 work의 한 실행 시도다.

5. **Execution resource is separable from capability**  
   누가 잘할 수 있는지(Worker/Agent), 어디서 실행되는지(Executor/Host), 어떤 provider/account/quota를 쓰는지는 독립적으로 교체 가능해야 한다.

6. **Source ownership survives centralization**  
   Eve, Manager, Discord, Git, Notion 등 기존 정본을 중앙 편의 때문에 복제 정본으로 만들지 않는다.

7. **Provenance before promotion**  
   lesson, skill, system improvement는 evidence와 evaluation 없이 전역 정본으로 승격하지 않는다.

8. **User interruption dominates background work**  
   P0 interactive work가 들어오면 background work는 안전한 경계에서 양보할 수 있어야 한다.

9. **Ask instead of fabricating**  
   project, cwd, mutation target, permission처럼 필수 정보가 없으면 추정으로 밀어붙이지 않는다.

10. **No fake integrations**  
    실제 연결·검증되지 않은 worker/tool/provider를 이름만 등록해 완성된 것처럼 취급하지 않는다.

## Current Position

2026-09-19 현재 위치는 **1차 완성 초반부**다.

이미 확보한 기반:

- Core contracts
- versioned pipeline runtime
- run/question persistence abstraction
- PostgreSQL migration
- event/trace
- worker registry
- Antigravity/OpenCode CLI adapters
- Discord edge policy/shadow experiment
- minimal authenticated Web surface
- initial scheduler/lesson/evaluation domain objects

중요한 구조적 수정:

- 기존의 `Request → Pipeline → Worker` 중심 모델 위에 `Goal/Work/Trigger` 계층을 둔다.
- Worker와 실제 실행 위치/계정/자원 풀을 분리할 수 있는 경계를 만든다.
- Artifact를 단순 문자열 ref가 아니라 장기 작업의 일급 metadata로 다룰 준비를 한다.
- in-memory WorkQueue를 최종 scheduler로 간주하지 않는다.
- Deferred라는 이유로 autonomy/self-improvement의 **아키텍처 요구사항**까지 미루지 않는다.

## Work Discipline

각 변경은 `inspect → plan → implement → test → inspect diff → verify` 순서로 수행한다.

작업 종료 시 적절한 event/decision/project state에 최소한 다음을 남긴다.

- 무엇을 바꿨는가
- 왜 바꿨는가
- 무엇을 검증했는가
- 결과
- 남은 문제
- architecture decision 발생 여부
- lesson 후보

거대한 누적 handover 문서를 history 원본으로 만들지 않는다.
