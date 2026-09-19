# 2차 완성 — Autonomous Personal & Project Operations

> Status: **Planned.** 1차 durable core가 acceptance criteria를 통과하기 전 production 범위로 확장하지 않는다.


## Definition of Done

2차가 끝나면 All Tomorrow는 사용자가 매번 버튼을 눌러야만 움직이는 중앙 요청 처리기가 아니다.

스케줄, watcher, 외부 사건과 기존 목표를 근거로 durable work를 스스로 발생시키고, background 실행을 지속하며, 프로젝트 간 검증된 lesson을 재사용하고, 학교·일정·리포트 같은 개인 운영까지 같은 중앙 흐름에서 다룰 수 있어야 한다.

또한 실행 중 resource availability/quota/rate-limit/cost/quality가 바뀌면 **pipeline별 예외처리가 아니라 generic observation → replanning**으로 대응해야 한다. 작업의 목표는 유지하되 policy에 따라 fallback, 품질/범위 축소, 병렬성 감소, 연기, 분할, 추가 자원 요청 중 적절한 선택을 할 수 있어야 한다.

자율성은 "아무거나 알아서 함"이 아니라 origin, budget, permission, provenance와 중단 가능성을 가진 work 생성이다.

## 1. Trigger Engine

지원 목표:

- cron/time schedule
- calendar-like one-shot schedule
- recurring schedule
- external event/webhook
- polling watcher
- condition watcher
- idle-resource trigger

모든 trigger는 직접 작업을 실행하는 대신 WorkItem을 생성하거나 기존 Goal을 깨운다.

필수:

- deduplication
- missed-run policy
- timezone
- enable/disable
- last/next fire
- provenance
- per-trigger budget/permission

## 2. Background Scheduler

1차 durable work scheduler를 확장한다.

- background concurrency control
- resource-aware dispatch
- interactive priority preemption/yield
- maintenance/research/experiment class
- backoff
- daily/weekly budget
- user quiet window where relevant
- long-running Goal progress

background work가 사용자의 interactive work를 굶기면 실패다.

## 3. Adaptive Planning and Graceful Degradation

1차의 Planner/PlanRevision/Observation contract를 실제 resource 상태와 연결한다.

### Replanning inputs

예:

- provider/account quota remaining
- rate-limit reset / concurrency ceiling
- worker/executor health
- current cost/budget
- latency/quality observations
- deadline/priority
- completed Work/Artifact
- policy constraints
- user approval requirements

이 값은 pipeline 내부 상수가 아니라 current state다.

### Failover before replanning

같은 capability, quality floor, privacy/risk, budget policy를 만족하는 다른 resource가 있으면 Execution Resolution이 concrete resource만 바꿀 수 있다. 이 경우 Work의 의미가 달라지지 않으므로 매번 새 PlanRevision을 만들 필요가 없다.

동등 failover로 해결되지 않고 계획 의미를 바꿔야 할 때 Replanner로 올린다.

### Generic replanning options

Planner는 policy가 허용하는 범위에서 다음을 조합할 수 있다.

- 더 저렴하거나 더 가벼운 model/tier로 변경
- 병렬성 또는 batch size 축소
- 낮은 우선순위 work 연기
- work를 더 작은 단위로 분할
- 이미 만든 artifact를 재사용해 남은 작업만 수행
- quality floor를 지킬 수 없으면 멈춤
- 추가 credential/resource가 필요하면 NEED_USER
- quota reset 시점까지 not-before를 두고 대기

이 선택지 자체도 특정 provider 이름에 묶지 않는다.

### Plan revision rules

- Goal과 acceptance criteria를 조용히 낮추지 않는다.
- 범위/품질 축소가 사용자 의도를 바꿀 정도면 정책상 사전 허용이 없는 한 NEED_USER.
- 완료된 work/artifact는 새 Plan에서 가능한 한 보존한다.
- 왜 replan했는지 observation과 rationale을 남긴다.
- 같은 failure가 반복되면 무한 replan하지 않고 bounded retry/decision policy를 적용한다.

## 4. Cross-Project Knowledge Loop

목표 흐름:

```text
run/event/artifact
      ↓
lesson candidate
      ↓
evidence + review/evaluation
      ↓
accepted lesson
      ↓
project bootstrap / task context candidate
      ↓
reuse outcome
      ↓
reuse evidence
```

초기 retrieval은 tag/metadata 기반이어도 된다.

pgvector/RAG는 실제 recall 문제가 확인될 때 추가한다.

Project bootstrap 시에는 accepted lesson을 곧바로 전역 사실로 박지 않고, 현재 프로젝트의 목표·제약과 맞는 후보를 provenance와 함께 골라 **bootstrap/context pack 후보**로 넣는다.

필수:

- provenance
- project/domain scope
- freshness/version
- conflict handling
- reuse count만이 아니라 실제 결과 개선 여부를 기록할 자리
- stale lesson retirement/review

## 5. Personal Operations

프로젝트 작업과 개인 운영을 같은 DB에 무차별 복제하지 않는다. 기존 owner를 adapter로 연결한다.

목표 흐름 예시:

### School material

프린트/사진/PDF ingress → artifact 등록 → extraction/classification pipeline → 기존 school/Manager owner에 저장 또는 reference → actionable item이 있으면 WorkItem 생성.

### Daily brief

학교/일정/할 일/진행 중 project/background 결과를 owner-aware 조회 → 하교 등 정해진 시점에 brief WorkItem 생성 → 사용자에게 전달.

### Manager query

사용자가 "뭐 해야 돼?"라고 물으면 중앙 project state와 Manager-owned personal state를 필요한 owner에서 읽어 Manager application이 응답한다.

## 6. Research Watchers

사용자가 즉시 요청하지 않아도 관심 영역을 조사할 수 있다.

Research topic도 고정 목록만 도는 방식으로 만들지 않는다. 반복 실패, resource 부족, user correction, architecture friction 같은 observation이 생기면 planner/evaluation layer가 **현재 시스템이 풀어야 할 연구 질문**을 만들 수 있어야 한다.

예:

- AI tool/service 변화
- game development 자료
- 접근 가능한 장문 문서·도서·reference material
- engine/plugin/library 변화
- asset sources
- community practices

필수 경계:

- research query/topic provenance: 왜 지금 이 주제를 조사했는지
- source/provenance
- duplicate suppression
- claim confidence
- 저장 목적 분류
- 지금 쓸 것과 aside/later 후보 분리
- research budget
- robots/terms/access constraint 준수

읽었다는 이유만으로 자동 global lesson으로 승격하지 않는다.

## 7. Service Experiment Framework

새 이미지 AI, LLM API, storage/tool service처럼 새로운 resource/tool이 발견되었을 때 바로 registry에 production-capable로 넣지 않는다.

이 framework는 서비스별 onboarding pipeline을 만드는 것이 아니라 **generic ResourceCandidate lifecycle**을 제공한다.

목표 단계:

```text
discovered
→ ResourceCandidate
→ capability / terms / prerequisites extraction
→ required user action? ──yes──> NEED_USER
→ credential/resource ref available
→ sandbox configuration
→ bounded experiment
→ captured artifacts/metrics
→ evaluated
→ candidate_available / rejected / watch
→ promotion policy가 허용하면 actual registry/resource-pool binding
```

예를 들어 무료 API가 새로 발견되어 API key 발급이 필요하면 시스템은 "provider X 전용 key 요청 코드"를 추가하는 대신 candidate의 `prerequisites`에 사용자 action을 기록하고 generic NEED_USER를 생성한다. 사용자가 key를 외부 secret owner에 등록한 뒤 opaque credential ref만 중앙에 연결한다.

필수:

- isolated credential/resource ref
- bounded test budget
- repeatable evaluation case
- output artifact retention
- failure reason
- provider terms/limits metadata
- capability / quota model / reset semantics / pricing class / auth prerequisite metadata
- 가입, key 발급, 결제, 약관 동의, 사용자 인증처럼 사용자가 직접 처리해야 하는 필수 단계가 생기면 우회하지 않고 해당 WorkItem을 NEED_USER로 전환
- user-facing question에는 왜 이 resource가 현재 Goal/Plan에 유용한지와 필요한 action만 전달하고 secret 값 자체를 chat/event에 복사하지 않음

## 8. Resource Pool Foundation

1차의 Worker/Executor/Provider Resource seam을 실제 라우팅에 사용한다.

관리 대상 예:

- local machine
- AWS host
- Sol Pi
- API providers
- account identities
- model endpoints
- free quota / paid budget
- concurrency/rate limit

credential secret 값은 외부 secret owner에 두고 중앙은 opaque ref와 usage metadata만 가진다.

2차에서는 "최저 비용 자동 최적화"까지 강제하지 않는다. 우선 availability, quota/capacity, rate-limit, permission, capability, quality floor를 기준으로 정상 라우팅하고, 상태 변화가 생기면 Planner에 observation을 보내 PlanRevision을 만들 수 있어야 한다.

resource pool은 provider별 switch문이 아니라 descriptor/state registry로 동작한다. 같은 capability를 만족하는 새 resource가 등록되면 generic candidate set에 자연스럽게 포함되어야 한다.

## 9. Artifact Catalog

장기 작업에서 산출물을 다시 찾고 사용할 수 있어야 한다.

지원 대상 예:

- reports
- source archives
- extracted school documents
- generated images
- evaluation datasets
- game assets
- builds
- logs
- structured data

중앙 DB는 artifact metadata와 provenance를 소유하며, bytes는 적절한 source/object storage owner에 둔다.

## 10. 2차 Acceptance Scenarios

### A. Proactive daily brief

사용자 요청이 없어도 정해진 시점에 trigger → WorkItem → owner-aware 조회 → brief 생성 → 전달. 재시작해도 다음 schedule을 잃지 않음.

### B. Research watcher

관심 주제 watcher가 새 후보를 발견 → 중복 제거 → research artifact 생성 → aside 또는 experiment candidate로 분류. 근거 없이 registry promotion하지 않음.

### C. New service evaluation

새 이미지 서비스 발견 → 제한된 sandbox test 여러 건 → artifact/metrics → usable 판정 시 registry candidate 등록.

### D. Resource fallback and plan revision

선호 executor/provider의 quota/health 문제 → generic observation 생성 → 동등 resource가 있으면 Execution Resolution이 transparent failover → 없거나 plan 의미 변경이 필요하면 같은 Goal에서 새 PlanRevision → 완료된 artifact 보존 → policy에 따른 축소/연기/분할/NEED_USER. trace/provenance는 이어짐.

### E. School material flow

사용자가 프린트 업로드 → artifact → extraction → 적절한 owner 저장/ref → actionable deadline 발견 시 WorkItem → daily brief에 반영.

### F. Cross-project reuse

새 프로젝트 시작 → 과거 accepted lesson 후보 자동 선택 → 적용 → 결과가 reuse evidence로 다시 기록.

### G. Image-service router flow

새 이미지 AI 서비스 발견 → background bounded test 여러 건 → 결과/비용/제약 artifact와 metric 기록 → usable candidate 판정 → 명시된 promotion policy를 통과하면 이미지 생성 router/registry에서 선택 가능한 provider로 추가. 이 연결을 위해 core 코드를 서비스별로 다시 뜯지 않음.

### H. Free asset collection

game-development watcher가 재사용 가능한 무료 asset 후보 발견 → source/license/provenance와 함께 artifact catalog에 등록 → 프로젝트 요구와 맞을 때 검색 가능. 출처·사용 조건을 모르는 파일을 "무료"로 단정해 축적하지 않음.

### I. No-request day

사용자가 하루 동안 새 요청을 보내지 않아도 이미 허용된 schedule/watcher/Goal에서 background work가 발생 → budget/priority 안에서 실행 → duplicate/runaway work 없이 결과를 artifact/lesson candidate/brief에 정리 → 사용자가 돌아오면 interactive request가 즉시 우선권을 가짐.

### J. Free-resource exhaustion

여러 background Work가 무료 API resource를 쓰는 중 quota가 거의 소진되거나 exhausted → pipeline YAML 수정 없음 → resource state/observation 갱신 → Planner가 낮은 priority work 연기, batch/parallelism 축소, 동일 capability의 다른 resource 사용 여부를 재계산 → Goal과 acceptance criteria는 유지.

### K. New free API requires user action

Research watcher가 현재 부족한 capability를 제공하는 새 free-tier API 발견 → ResourceCandidate 생성 → 가입/API key 발급 prerequisite 식별 → 사용자에게 NEED_USER로 필요한 action과 이유 요청 → 사용자가 credential을 secret owner에 등록 → opaque ref 연결 → bounded validation → usable이면 resource pool candidate로 편입. provider 이름을 generic planner/pipeline code에 추가하지 않음.

### L. Generic resource adapter swap

동일 capability의 테스트 provider A/B를 서로 다른 raw quota error와 auth 방식으로 연결 → 각 adapter가 공통 observation/prerequisite contract로 정규화 → 같은 Planner/Policy/Service Experiment lifecycle이 두 provider 모두에서 작동.

## 11. Explicitly Not Required for 2차

- system code의 무인 production promotion
- 무제한 웹 크롤링
- 무제한 provider account rotation
- 완전 자동 비용 차익 최적화
- 모든 provider의 quota API를 하나의 강제 schema로 완벽히 표준화
- 사용자 승인 없이 새 계정/credential을 임의 생성하거나 약관에 동의하는 자동화
- 장기 게임 제작을 항상 수행하는 정책
- self-generated benchmark만으로 자기 개선 확정
- multi-region HA

이 단계의 핵심은 자율성의 양이 아니라 **durable하고 설명 가능하며 중단 가능한 자율 운영**이다.
