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

1차/2차/3차는 날짜나 단순 버전 번호가 아니라 **capability milestone**이다. 파일이 생겼거나 mock test가 통과했다는 이유만으로 다음 단계 완료로 올리지 않고, 각 문서의 end-to-end acceptance scenario가 실제 운영 조건에서 통과해야 한다.

후속 단계의 schema/interface prototype은 앞 단계에서 만들 수 있지만, 앞 단계의 durability/ownership invariant를 건너뛰고 production 기능부터 활성화하지 않는다.

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

## Original Vision Coverage

원문 요구가 추상화 과정에서 사라지지 않도록 completion stage를 직접 연결한다.

| 원문에서 요구한 결과 | 주 stage | 닫히는 기준 |
|---|---|---|
| 어느 기기에서든 웹으로 중앙 접속 | 1차 | remote HTTPS control surface + durable DB/recovery |
| 범용 답변이 아닌 사용자 맥락 기반 질의응답 | 1차 | Manager/source-owner context를 조립한 Web 질의 경로 |
| 흩어진 ChatGPT/Discord/CLI 작업을 중앙에서 조정 | 1차 | 공통 Goal/Work/Run authority + edge ingress |
| 한 곳에서 다른 프로젝트의 실제 수정까지 이어짐 | 1차 | cross-system project resolution → WorkItem → adapter/worker execution |
| Discord가 모든 말을 무조건 중앙으로 보내지 않음 | 1차 | local-vs-central edge policy + actual escalation |
| pipeline을 중앙에서 모듈식으로 교체 | 1차 | immutable/versioned pipeline recipe와 work 분리 |
| 필수 정보가 없으면 즉시 사용자에게 질문 | 1차 | durable NEED_USER + restart-safe resume |
| 과거 전체 과정을 못 본 worker의 handover 격차 감소 | 1차 | project coordination projection + provenance-aware context pack |
| 프로젝트 노하우를 다음 프로젝트에 재사용 | 1차→2차 | 1차 manual lesson/bootstrap, 2차 outcome 기반 지속 loop |
| 스케줄/요청 없이 background work 지속 | 2차 | durable trigger + background scheduler |
| 커뮤니티·도서·자료를 조사해 지식 축적 | 2차 | research watcher + evidence/artifact + lesson candidate |
| 지금 안 쓰는 유용한 정보를 aside로 분류 | 2차 | research classification / backlog knowledge |
| 새 이미지 AI를 background에서 몇 번 시험하고 router에 편입 | 2차→3차 | 2차 bounded experiment + promotion policy로 router binding, 3차 measured self-improvement와 자동 최적화 |
| 무료 게임 asset 수집 | 2차 | watcher → artifact catalog with source/provenance |
| 학교 프린트 스캔·저장·실행항목 생성 | 2차 | school material end-to-end artifact/extraction/owner/work flow |
| 하교시간에 오늘 report와 할 일 선제 전달 | 2차 | scheduled owner-aware daily brief |
| 여러 API key/계정/기기/서버 자원 활용 | 2차→3차 | 2차 resource pool/fallback, 3차 quota/cost/quality optimization |
| 유휴 무료 자원으로 제대로 된 game demo 제작 | 3차 | multi-day Goal/Work graph → playable build → user feedback iteration |
| 시스템이 성과·실패를 보고 스스로 개선 | 3차 | proposal → sandbox → evaluation → promotion/monitoring/rollback |

2차의 service experiment가 통과했다고 곧바로 무인 production 변경을 허용한다는 뜻은 아니다. 2차에서는 candidate 등록과 명시된 promotion policy까지, production self-improvement의 닫힌 자동 loop는 3차에서 검증한다.

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

## Roadmap Maintenance

- README의 Original Vision 원문은 요약문으로 대체하지 않는다.
- Derived Final Goals를 추가·병합·삭제하면 Original Vision Coverage 표와 completion-stage acceptance를 같은 변경에서 함께 갱신한다.
- stage 이동은 "나중에 하자"라는 이유만으로 원문 요구를 삭제하는 행위가 아니다. 어느 stage에서 닫히는지 포인터가 남아야 한다.
- 새 기능 제안이 최종 목적과 직접 연결되지 않으면 기본적으로 backlog 후보이며 core architecture에 즉시 넣지 않는다.
- 실제 구현이 문서와 달라졌으면 완료했다고 쓰기 전에 Current Position/Architecture/해당 stage 문서를 갱신한다.

## Architecture Decisions

- [ADR 0001 — Separate Control Plane Repository](decisions/0001-control-plane-boundary.md)
- [ADR 0002 — Durable Work Above Pipeline](decisions/0002-durable-work-above-pipeline.md)

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
