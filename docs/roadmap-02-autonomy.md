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

1차의 Planner / Execution Resolution 경계를 실제 resource 상태와 연결한다.

resource state에는 quota/rate-limit, health, cost, quality, priority, deadline 같은 현재 조건이 들어갈 수 있다. 정확한 quota를 알 수 없으면 unknown/estimated + freshness로 충분하다.

처리 순서:

1. 같은 capability와 policy를 만족하는 동등 resource가 있으면 safe failover
2. 없고 Plan 의미를 바꿔야 하면 Planner가 남은 Work를 다시 계산
3. 가능한 대응은 병렬성/batch 축소, 낮은 우선순위 연기, Work 분할, quota reset까지 wait, 기존 artifact 재사용, 추가 resource 요청 등
4. Goal/acceptance criteria를 실질적으로 낮춰야 하면 사전 policy가 없는 한 NEED_USER

완료된 Work/Artifact는 보존하고 같은 failure에 무한 replan하지 않는다.

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

새 AI/API/tool service가 발견되었다고 바로 production resource로 넣지 않는다.

범용 흐름:

```text
discover
→ usefulness / duplication / risk / user-effort 판단
→ 필요한 user action이 있으면 NEED_USER
→ bounded sandbox test
→ artifact/metric 평가
→ available / watch / rejected
```

이미 지원하는 protocol이면 config/metadata만으로 연결하고, 새로운 protocol이면 core/pipeline 분기가 아니라 별도 adapter implementation work로 분리한다.

모든 후보에 가입/key 발급을 요구하지 않는다. 현재 capability 부족을 실제로 메우고 기대 효용이 충분한 후보에만 사용자 action을 요청한다.

Raw API key는 chat/event에 받지 않는다. external secret owner에 등록하고 opaque credential ref만 사용한다.

## 8. Resource Pool Foundation

Worker/Executor/Provider Resource seam을 실제 라우팅에 사용한다.

관리 대상은 local/AWS/Sol Pi 같은 host, API/model/account, free quota/paid budget, concurrency/rate limit 등이다.

resource pool은 provider별 switch문이 아니라 metadata/state registry로 동작한다. 같은 capability를 만족하는 새 resource가 등록되면 기존 candidate set에 들어가야 한다.

정확한 quota telemetry가 없는 resource도 recent success/failure와 freshness를 이용해 conservative state로 운영할 수 있다.

credential 값은 외부 secret owner에 두고 중앙에는 opaque ref만 둔다.

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

선호 executor/provider의 quota/health 문제 → generic observation 생성 → 동등 resource가 있으면 Execution Resolution이 transparent failover → 없거나 plan 의미 변경이 필요하면 같은 Goal에서 새 Plan revision → 완료된 artifact 보존 → policy에 따른 축소/연기/분할/NEED_USER. trace/provenance는 이어짐.

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

### J. Resource adaptation and acquisition suite

실제 autonomous resource 운영은 아래를 함께 통과해야 한다.

- **free quota exhaustion**: quota가 줄거나 exhausted되어도 pipeline 수정 없이 동등 failover 또는 낮은 우선순위 연기·batch/parallelism 축소·wait 같은 plan adjustment가 일어남
- **useful new free API**: watcher가 부족한 capability의 free-tier API를 발견 → public metadata로 효용/중복/risk/user-effort 평가 → 가치가 있을 때만 사용자에게 가입/key 발급을 NEED_USER로 요청 → raw key는 chat에 받지 않고 secret owner의 credential ref만 연결 → bounded validation 후 pool 후보가 됨
- **not worth interrupting**: 중복되거나 효용이 낮은 후보는 aside/watch로 남고 사용자에게 key 발급 요청을 보내지 않음
- **declarative onboarding**: 이미 지원하는 protocol이면 endpoint/model/config + credential ref만으로 연결되고 core/pipeline 수정 없음
- **custom protocol**: 새로운 protocol이면 core branch가 아니라 별도 adapter implementation work로 분리되어 sandbox 검증 후 등록 후보가 됨
- **ambiguous mutation**: timeout 뒤 side effect가 불명확하면 resource B로 즉시 중복 실행하지 않고 reconciliation/idempotency 확인 후 retry/NEED_USER 판단


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
