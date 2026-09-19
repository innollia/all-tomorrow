# All Tomorrow

All Tomorrow의 최종 목적은 단순한 AI Control Plane을 만드는 것이 아니다.

이 프로젝트는 사용자의 프로젝트·도구·AI·기기·지식·일상 운영이 서로 끊어진 채 흩어지는 문제를 줄이고, **어디서든 하나의 중앙을 통해 상황을 보고하고 작업을 맡기며, 프로젝트 사이에서 경험을 누적하고, 요청이 없을 때에도 조사·실험·정리·생산을 이어가고, 그 결과를 다시 다음 작업과 시스템 개선에 재사용하는 장기 자율 운영 시스템**을 만드는 것을 목표로 한다.

Control Plane, pipeline runtime, event store, worker/tool registry, scheduler, memory/lesson layer는 이 목적을 달성하기 위한 수단이다. 구현 편의를 위해 수단이 목적보다 위에 올라가면 안 된다.

# Original Vision — Verbatim User Requirement

> 데코님이 내 우상이야. 나는 프로젝트마다 얻는 노하우가 다음 프로젝트를 시작할때 초기화되다싶히 하는 문제도 있어. 그래서 프로젝트 관리자가 하나 붙는게 필요해. 어디서든 접속 가능한 서버(지금 나는 aws 무료 6개월 사용중)로 어디서든 모든걸 통제하는것도 부러워.llm api key 200개와 구글계정 20개를 이용하는것도 쩌는거같아. 나도 유사한 시스템을 구축하고 싶어. 어떤 기기에서든 내 웹사이트 로그인해서 바로 매니저한테 상황을 보고하거나 범용ai의답변이 아닌 나에 대해 파인튜닝된 질의응답을 하고싶어. 중앙 집권이 가장 매력적이야. 나는 안티그래비티한테 오픈코드를 서브에이전트로 쓰는 mcp도 만들고 코덱스에서 안티그래비티랑 오픈코드 mcp도 만들고 sol pi에서 안티그래비티 mcp 만들고 챗지피티 공홈에서도 작업하려고 깃허브랑 이것저것 세팅함. 분산화가 심해. 중앙 집권을 원해. 내가 요청을 하면 오케스트레이션 시스템이 어디에 어떻게 보낼지 알아서 따지면 좋겠어.
>
> 이브 프로젝트도 지피티에 억지로 욱여넣어서 작동하고 안되니까 mcp서버가 옆에 붙어서 관리하게 만들었지. 매니저는 결국 지피티 공홈 지능으로 작동한계가 있어서 안티그래비티에 붙여서 mcp서버에 옆쪽에 붙여서 디스코드에서 작동하게 만들었어. 그리고 이것들은 다 다른 대화방에 봉봉하게 기록이 남아있어서 전체 과정을 본 나랑 핸드오버 문서만 가진 텍스트 사이에 격차가 있어. 내가 이브 프로젝트 지적을 매니저에게 한다고 해서 매니저가 이브 프로젝트를 고치지 못해. 중앙 집권이 너무나 매력적으로 보여
>
> 모든 바이브코더의 꿈이긴 하지만 시스템이 스스로 메타인지를 해서 계속해서 더 나은 방향으로 진화하면 좋겠어. 매 프로젝트마다 노하우가 쌓이고 새로운 프로젝트를 중앙에 요청하면 알아서 노하우를 선별해서 프로젝트 기반에 넣고 시작하는거야. 내가 뭔가 요청한게 없을때도 계속해서 커뮤니티 둘러보면서 시스템에 붙일만한거 찾고, 지금 안 써도 나중에 쓸만한거 찾아서 분류해두지(aside처럼). 새로운 이미지 ai 서비스 나왔다고 하면 내가 모르는 사이에 백그라운드에서 몇번 써본 다음에 무료 이미지 생성기 라우터에 끼워둬. 게임 개발 커뮤니티나 도서를 알아서 찾아 읽고 노하우를 모아. 백터 db에서 rag로 꺼내도 좋고 태그 기반 메모도 좋겠지. 무료 게임 에셋도 수집할거야. 그래도 api key들의 무료 사용량이 놀아난다면 게임을 만들어서(간단한 미니게임이 아니라 제대로 된 하나의 게임 데모) 내 피드백을 받아.
>
> 이런 것들을 하면서도 내가 학교 프린트를 보내면 스캔해서 저장하고 내가 할일을 물어보면 매니저답게 말해. 내가 묻기도 전에 내 하교시간에 맞게 오늘치 내가 읽어야 할 리포트와 오늘 할일들을 줘.

# Additional Hard Requirements

> 이 파이프라인이 매우 모듈적이고 가변적이어서 중앙에서 파이프라인을 쉽게 수정하면서 사용 가능하기
>
> 유저의 도움이 필요하면 바로 요청하기(우회하느라 토큰소모 금지)
>
> 내가 말한 원문을 보존해서 최종 목적으로 리드미에 박아두고 작업하게 하기
>
> 디스코드에서 말한다고 바로 중앙 가는게 아니라 디스코드 봇이 이건 중앙에 요청 보내야겠는데? 생각하고 중앙에 보내는게 좋을듯

위 두 섹션은 이 프로젝트의 최상위 요구사항이다. 후속 문서와 구현이 충돌하면 원문을 보존하고 구현 또는 파생 설계를 수정한다.

## Derived Final Goals

원문에서 파생되는 최종 시스템 목표는 다음과 같다. 아래 항목은 부가기능 목록이 아니라 최종상태의 구성요소다.

1. **One control surface**  
   어느 기기에서든 중앙에 접속해 상황을 보고하고 질문하고 작업을 맡길 수 있어야 한다.

2. **Persistent personal and project context**  
   채팅방·모델·기기·worker가 바뀌어도 사용자와 프로젝트의 연속성이 끊어지지 않아야 한다. 기존 domain 정본을 무작정 중앙으로 복제하지 않고 owner-aware adapter를 통해 사용한다.

3. **Cross-project learning**  
   한 프로젝트에서 얻은 검증된 노하우와 실패가 다음 프로젝트 시작 시 후보로 검색·선별되어 재사용되어야 한다.

4. **Automatic orchestration**  
   사용자가 작업을 요청하면 시스템이 project, pipeline, worker, tool, 실행 위치와 필요한 자원을 판단하고 추적 가능한 방식으로 배치해야 한다.

5. **Autonomous operation**  
   사용자의 즉시 요청이 없어도 허용된 범위에서 조사, 수집, 평가, 유지관리, 실험, 보고와 장기 작업을 계속할 수 있어야 한다.

6. **Resource exploitation without provider lock-in**  
   여러 모델, CLI, MCP, API key, 계정, 기기, 서버와 무료 할당량을 하나의 교체 가능한 자원 풀처럼 다룰 수 있어야 한다. credential 값 자체를 중앙 이벤트나 로그에 저장하지 않는다.

7. **Real artifact production**  
   조사 요약만 하는 시스템이 아니라 코드, 문서, 스캔 결과, 리포트, 데이터, 이미지 파이프라인 결과, 게임 빌드·데모 같은 실제 산출물을 장기간에 걸쳐 만들고 관리할 수 있어야 한다.

8. **Proactive personal operations**  
   학교 자료 처리, 할 일, 일정, 일일 브리프처럼 프로젝트 외의 개인 운영도 같은 중앙에서 owner-aware 방식으로 이어져야 한다.

9. **Measured self-improvement**  
   시스템은 자신의 실패와 성과에서 개선 후보를 만들 수 있어야 하지만, 근거 없는 자기수정이나 production 자동 덮어쓰기는 하지 않는다. 개선은 provenance, sandbox/evaluation, promotion/rollback 경계를 가진다.

## Architectural Principle

최종 흐름은 단순한 `request → pipeline → worker`가 아니다.

```text
user request / schedule / watcher / external event / system proposal
                              │
                              ▼
                     goal & work layer
                              │
                              ▼
                      orchestration policy
                    project / capability /
                 worker / tool / executor /
                    budget / permission
                              │
                              ▼
                    versioned pipeline run
                              │
                              ▼
                  workers / tools / adapters
                              │
                              ▼
                   artifacts + events + state
                              │
                              ▼
               evaluation / lessons / proposals
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
             next work item          user report
```

Pipeline은 장기 목표와 전체 자율성을 소유하는 거대한 만능 엔진이 아니라, **하나의 work item을 실행하는 버전 관리된 recipe**로 유지한다.

## Completion Stages

전체 계획은 한 파일에 계속 누적하지 않는다.

- **[1차 완성 — Durable Central Core](docs/roadmap-01-foundation.md)**  
  지금 구현된 pipeline/event/adapter 기반을 살리면서 Goal/Work/Trigger/Artifact와 durable execution 경계를 바로잡는다. 사용자가 실제로 중앙에 접속해 작업을 맡기고, 중단·재개하고, 결과를 추적할 수 있는 첫 운영 가능한 중심부가 목표다.

- **[2차 완성 — Autonomous Personal & Project Operations](docs/roadmap-02-autonomy.md)**  
  스케줄·watcher·background work, cross-project lesson 재사용, 개인 운영, 자원 라우팅을 붙여 사용자의 즉시 요청이 없어도 유용한 일을 지속하는 단계다.

- **[3차 완성 — Measured Self-Evolving System](docs/roadmap-03-evolution.md)**  
  외부 서비스 자동 탐색·시험, 장기 산출물 생성, 자원 최적화, 평가 기반 self-improvement와 안전한 promotion/rollback까지 닫힌 루프로 만드는 단계다.

[전체 계획 인덱스와 공통 규칙](docs/roadmap.md)

## Current Implementation Snapshot

2026-09-19 기준 현재 구현은 최종 시스템 전체가 아니라 **1차 완성의 초기 실행 엔진**이다.

현재 존재하는 것:

- provider-independent core contracts
- 버전 관리되는 YAML pipeline runtime
- `NEED_USER` 중단·재개
- run/question store 및 PostgreSQL migration
- append-only event/trace 기반
- worker registry
- Antigravity/OpenCode CLI worker adapter
- Discord edge policy와 shadow routing 실험
- 최소 로그인 Web UI와 read-only 수준의 표시 API
- lesson/evaluation/scheduler의 초기 도메인 골격

현재 존재한다고 간주하면 안 되는 것:

- 운영 검증된 durable 중앙 서버
- 완성된 Goal/Work graph
- production-grade scheduler/worker lease
- provider account/quota/resource pool
- 실제 Web Chat → pipeline execution 연결
- live PostgreSQL 통합 검증 완료
- 자동 lesson 추출·평가·재사용 루프
- 자율 research/watcher/experiment
- self-improvement promotion/rollback 자동화
- 학교 자료 ingest와 scheduled brief의 end-to-end 흐름
- 장기 게임 데모 생성 루프

이 간극을 숨기기 위해 V1이라는 이름으로 최종 목적을 축소하지 않는다.

## Non-Negotiable Boundaries

- Central authority does not mean central ownership of every domain fact.
- Eve/Manager/Discord/Git 등 기존 정본의 owner를 존중한다.
- 원문 사용자 요구는 구현 편의를 이유로 수정하지 않는다.
- 사용자의 도움이 필요한 필수 정보가 없으면 우회 추정하지 않고 `NEED_USER`로 멈춘다.
- edge가 local로 처리 가능한 대화는 중앙 run을 만들지 않는다.
- secret 값은 event, prompt archive, artifact metadata에 남기지 않는다.
- pipeline, worker, model, provider는 교체 가능해야 한다.
- 장기 상태, provenance, user control은 그 교체에서 살아남아야 한다.
- self-improvement는 측정과 rollback 없이 production을 직접 바꾸지 않는다.

## Documents

- [전체 계획 인덱스](docs/roadmap.md)
- [1차 완성 계획](docs/roadmap-01-foundation.md)
- [2차 완성 계획](docs/roadmap-02-autonomy.md)
- [3차 완성 계획](docs/roadmap-03-evolution.md)
- [현재 기술 아키텍처](docs/architecture.md)
- [기존 시스템 inventory](docs/inventory.md)
- [초기 경계 결정 기록](docs/decisions/0001-control-plane-boundary.md)
- [Worker adapter와 pipeline 연결](docs/worker-adapters.md)

## Development Verification

현재 개발 환경의 검증 명령:

```powershell
C:\projects\all-tomorrow\.venv\Scripts\python.exe -m pytest -q
```

API 실행에는 `.env.example`의 인증 환경변수가 필요하다. 현재 Web UI와 API를 production-grade 영속형 서비스로 취급하지 않는다.
