# 2차 완성 — Autonomous Personal & Project Operations

## Definition of Done

2차가 끝나면 All Tomorrow는 사용자가 매번 버튼을 눌러야만 움직이는 중앙 요청 처리기가 아니다.

스케줄, watcher, 외부 사건과 기존 목표를 근거로 durable work를 스스로 발생시키고, background 실행을 지속하며, 프로젝트 간 검증된 lesson을 재사용하고, 학교·일정·리포트 같은 개인 운영까지 같은 중앙 흐름에서 다룰 수 있어야 한다.

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

## 3. Cross-Project Knowledge Loop

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

필수:

- provenance
- project/domain scope
- freshness/version
- conflict handling
- reuse count만이 아니라 실제 결과 개선 여부를 기록할 자리
- stale lesson retirement/review

## 4. Personal Operations

프로젝트 작업과 개인 운영을 같은 DB에 무차별 복제하지 않는다. 기존 owner를 adapter로 연결한다.

목표 흐름 예시:

### School material

프린트/사진/PDF ingress → artifact 등록 → extraction/classification pipeline → 기존 school/Manager owner에 저장 또는 reference → actionable item이 있으면 WorkItem 생성.

### Daily brief

학교/일정/할 일/진행 중 project/background 결과를 owner-aware 조회 → 하교 등 정해진 시점에 brief WorkItem 생성 → 사용자에게 전달.

### Manager query

사용자가 "뭐 해야 돼?"라고 물으면 중앙 project state와 Manager-owned personal state를 필요한 owner에서 읽어 Manager application이 응답한다.

## 5. Research Watchers

사용자가 즉시 요청하지 않아도 관심 영역을 조사할 수 있다.

예:

- AI tool/service 변화
- game development 자료
- engine/plugin/library 변화
- asset sources
- community practices

필수 경계:

- source/provenance
- duplicate suppression
- claim confidence
- 저장 목적 분류
- 지금 쓸 것과 aside/later 후보 분리
- research budget
- robots/terms/access constraint 준수

읽었다는 이유만으로 자동 global lesson으로 승격하지 않는다.

## 6. Service Experiment Framework

새 이미지 AI나 도구가 발견되었을 때 바로 registry에 production-capable로 넣지 않는다.

목표 단계:

```text
discovered
→ candidate
→ sandbox configuration
→ bounded experiment
→ captured artifacts/metrics
→ evaluated
→ available / rejected / watch
```

필수:

- isolated credential/resource ref
- bounded test budget
- repeatable evaluation case
- output artifact retention
- failure reason
- provider terms/limits metadata

## 7. Resource Pool Foundation

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

2차에서는 "최저 비용 자동 최적화"까지 강제하지 않는다. 우선 availability, quota exhaustion, permission, capability를 기준으로 정상 라우팅한다.

## 8. Artifact Catalog

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

## 9. 2차 Acceptance Scenarios

### A. Proactive daily brief

사용자 요청이 없어도 정해진 시점에 trigger → WorkItem → owner-aware 조회 → brief 생성 → 전달. 재시작해도 다음 schedule을 잃지 않음.

### B. Research watcher

관심 주제 watcher가 새 후보를 발견 → 중복 제거 → research artifact 생성 → aside 또는 experiment candidate로 분류. 근거 없이 registry promotion하지 않음.

### C. New service evaluation

새 이미지 서비스 발견 → 제한된 sandbox test 여러 건 → artifact/metrics → usable 판정 시 registry candidate 등록.

### D. Resource fallback

선호 executor/provider의 quota/health 문제 → 같은 WorkItem을 capability가 맞는 다른 자원으로 안전하게 재배치. trace는 이어짐.

### E. School material flow

사용자가 프린트 업로드 → artifact → extraction → 적절한 owner 저장/ref → actionable deadline 발견 시 WorkItem → daily brief에 반영.

### F. Cross-project reuse

새 프로젝트 시작 → 과거 accepted lesson 후보 자동 선택 → 적용 → 결과가 reuse evidence로 다시 기록.

## 10. Explicitly Not Required for 2차

- system code의 무인 production promotion
- 무제한 웹 크롤링
- 무제한 provider account rotation
- 완전 자동 비용 차익 최적화
- 장기 게임 제작을 항상 수행하는 정책
- self-generated benchmark만으로 자기 개선 확정
- multi-region HA

이 단계의 핵심은 자율성의 양이 아니라 **durable하고 설명 가능하며 중단 가능한 자율 운영**이다.
