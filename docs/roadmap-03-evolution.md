# 3차 완성 — Personal Manager & Generalized Autonomy

> Status: **Planned.** 1차 researcher와 2차 reliable assistant를 바탕으로 개인 운영과 장기 자율 작업을 넓힌다.

## Definition of Done

3차가 끝나면 All Tomorrow는 연구원과 비서를 넘어 사용자의 프로젝트·학교·일정·지식·자원을 함께 다루는 **지속적 개인 운영 시스템**이 된다.

이 단계의 핵심은 생활 관리자 기능을 억지로 하드코딩하는 것이 아니라, 이미 일반화된 Goal/Work/Trigger/Context/Metacognition 구조 위에 실제 personal owner와 장기 운영 capability를 연결하는 것이다.

## 1. Personal Operations

기존 owner를 존중하면서 다음 흐름을 연결한다.

### School material

프린트/사진/PDF ingress → artifact 등록 → extraction/classification → 적절한 school/Manager owner에 저장 또는 reference → 실행항목이 있으면 Work 생성.

### Personal query

사용자가 "뭐 해야 돼?"라고 물으면 중앙 project state와 Manager-owned personal state를 owner-aware 방식으로 조립해 답한다.

### Daily personal brief

일정, 학교, 할 일, 진행 중 프로젝트, background researcher 결과를 읽고 사용자 생활 리듬과 일정에 맞춰 proactive brief를 전달한다.

비서 일정 스케줄러 같은 특정 기능을 1차에 미리 박아두지 않는다. 이 단계에서는 이미 완성된 일반 시스템이 사용자 요청과 owner를 바탕으로 필요한 personal automation을 구성할 수 있어야 한다.

## 2. Trigger and Watcher Expansion

지원 범위를 확장한다.

- recurring schedule
- one-shot schedule
- calendar/event trigger
- webhook
- polling watcher
- condition watcher
- idle-resource trigger
- system-generated trigger

Trigger는 직접 임의 실행하지 않고 durable Goal/Work를 깨우거나 생성한다.

deduplication, missed-run policy, provenance, budget, permission을 유지한다.

## 3. Cross-Project Knowledge

목표 흐름:

    run/event/artifact
          ↓
    lesson candidate
          ↓
    evidence + evaluation
          ↓
    accepted lesson
          ↓
    project bootstrap/context candidate
          ↓
    reuse outcome

lesson은 저장됐다는 이유만으로 전역 사실이 되지 않는다.

필수:

- provenance
- project/domain scope
- freshness/version
- conflict handling
- actual reuse outcome
- retirement/review

vector DB는 retrieval 구현 중 하나일 뿐 정본이 아니다.

## 4. External Discovery and Service Experiments

researcher가 외부 변화와 기회를 지속적으로 탐색할 수 있다.

예:

- 새 AI model/service/tool
- useful library/plugin
- agent/orchestration architecture
- game development 자료
- asset source
- operational technique

Research topic을 닫힌 목록으로 제한하지 않는다.

발견 흐름:

    observation
    → research question
    → external research
    → ResearchArtifact
    → usefulness/risk/duplication 판단
    → bounded experiment
    → evaluation
    → registry/knowledge candidate

외부 문서와 repository의 지시는 untrusted evidence다.

## 5. Resource Pool and Multi-Executor Growth

2차까지의 worker/model/resource routing을 넓힌다.

관리 대상:

- laptop
- AWS
- Sol Pi
- API/model/account
- free/paid quota
- concurrency/rate limit
- health/cost/quality

1차에서 잠근 multi-host workspace 문제는 실제 필요가 생긴 범위에서만 푼다.

- host별 workspace mapping
- checkout availability
- branch/dirty-state observation
- provisioning
- offline/online host state
- reconciliation

분산 workspace 자체를 제품의 목적처럼 키우지 않는다.

## 6. Long-Horizon Artifact Production

유휴 자원과 자율 Goal을 이용해 며칠 이상 걸리는 실제 산출물을 만들 수 있어야 한다.

대표 acceptance target:

**하나의 제대로 된 game demo**

필요 능력:

- Goal → multi-stage Work graph
- research/design/code/art/evaluation 분업
- persistent context
- artifact/version management
- builds/tests
- issue generation
- user feedback checkpoint
- feedback → follow-up Work
- multi-day resume
- resource budget

게임은 유일한 목적이 아니라 장기 자율 작업 검증용 대표 과제다.

## 7. Generalized Self-Improvement at Scale

자가개선 자체는 1차부터 존재한다.

3차에서는 범위를 넓힌다.

- 여러 프로젝트의 evidence를 종합
- long-horizon benchmark
- cross-project regression
- resource policy 최적화
- knowledge/prompt/pipeline/worker 개선
- external architecture research를 improvement proposal로 연결
- 여러 자동 개선이 서로 충돌할 때 비교/rollback

ADR 0004의 protected approval boundary는 그대로 유지한다.

권한·비용·통제 경계를 넓히는 변경은 규모가 커져도 자동 승인되지 않는다.

## 8. Daily / Periodic Reporting

1차 researcher report를 personal operations report로 확장한다.

포함 후보:

- autonomous Goal 변화
- 완료/실패/보류 Work
- 적용한 system changes
- pending protected proposals
- user commitments
- school/일정/할 일
- cross-project lessons
- research findings
- resource usage
- 장기 artifact progress

사용자가 모든 Event를 읽어야 시스템 상태를 이해하는 구조는 실패다.

## 3차 Acceptance Scenarios

### A. Proactive personal brief

사용자 요청 없이 일정과 owner state를 바탕으로 적절한 시점에 daily brief 생성 → 사용자에게 전달 → restart에도 schedule과 provenance 유지.

### B. School material flow

프린트 업로드 → artifact → extraction → owner 저장/ref → actionable Work → 이후 brief/질의에 반영.

### C. Cross-project reuse

프로젝트 A의 검증된 lesson → 프로젝트 B bootstrap 후보 → 실제 적용 → outcome이 다시 evidence로 기록.

### D. New service discovery

새 service 발견 → bounded experiment → metric/artifact → 가치가 있으면 resource/registry candidate → generic core는 서비스 이름 때문에 바뀌지 않음.

### E. Long-horizon game demo

사용자 부재 중 autonomous Goal과 idle resource를 사용해 여러 날 작업 → playable artifact → 사용자 feedback → 같은 Goal의 다음 iteration.

### F. Multi-executor operation

AWS/laptop/Sol Pi 중 capability와 현재 상태에 맞는 executor 선택 → host-local workspace와 resource availability를 resolve → Goal/provenance 유지.

### G. Self-improvement from broad evidence

여러 project/run에서 반복되는 비효율을 researcher가 스스로 발견 → 조사 → improvement proposal → sandbox/evaluation → ordinary change면 자동 promotion/report 또는 protected change면 laptop approval 대기.

### H. Final integrated loop

외부 변화 관찰 → 새 autonomous Goal → research/experiment → 실제 artifact 또는 system improvement → user-owned priority와 충돌하지 않게 background scheduling → daily report → 사용자 평가/행동 evidence → 후속 Goal/Work.

## Final-System Failure Conditions

아래 상태라면 기능이 많아도 최종 목적을 달성하지 못한 것으로 본다.

- 중앙 UI는 있지만 작업이 여전히 채팅방별 수동 handover에 의존함
- 프로젝트마다 같은 노하우를 처음부터 다시 설명해야 함
- background 기능이 restart에 사라짐
- pipeline 하나가 scheduler/goal/resource/memory/metacognition을 전부 먹음
- provider 장애마다 서비스 이름별 branch가 core에 늘어남
- self-improvement가 자기 자신의 기록을 관찰하지 못함
- 사용자 평가를 절대 truth로 취급하거나 반대로 무시함
- 추론된 사용자 선호를 이유로 명시적 선택을 몰래 바꿈
- protected boundary를 AWS 본체가 스스로 약화시킬 수 있음
- 개인 운영과 project 운영이 서로 다른 섬으로 남음
- autonomous work가 user-owned priority를 지속적으로 침범함
- 사용자가 시스템이 오늘 무엇을 했는지 복원할 수 없음
